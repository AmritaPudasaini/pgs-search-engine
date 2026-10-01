"""Query-independent ranking signals: `page_scores` and the link figures on `domain_stats`.

`refresh_scores` rebuilds them from what is already stored -- no Spark job needed:

- **Link graph**: each canonical page's latest crawl (`crawled_documents.links`),
  resolved to the canonical page each link points at. A link to a duplicate counts
  for its canonical page; self-links are dropped; one edge per (source, target).
- **PageRank** by power iteration (damping 0.85), with dangling pages spreading their
  rank evenly. Held in memory: fine to a few million pages; past that, move this one
  step to Spark and keep the same output table.
- **Freshness**: halves every `FRESHNESS_HALF_LIFE_DAYS`, from `published_at`, else
  the last time the page was seen.
- **Quality**: grows with word count up to `QUALITY_FULL_WORDS`, minus
  `QUALITY_FLAG_PENALTY` for each ETL quality flag.
- **Static rank**: the blend in `STATIC_RANK_WEIGHTS`, every input scaled 0..1.

`ranking_features` hands the reranker these signals for a set of pages.
"""

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Float, Integer, bindparam, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import DomainStats, Page, PageScore, search_documents

DAMPING = 0.85
MAX_ITERATIONS = 100
TOLERANCE = 1e-8  # L1 change between iterations
FRESHNESS_HALF_LIFE_DAYS = 180.0
QUALITY_FULL_WORDS = 1000
QUALITY_FLAG_PENALTY = 0.25
STATIC_RANK_WEIGHTS = {
    "pagerank": 0.4,
    "domain_authority": 0.2,
    "quality": 0.2,
    "freshness": 0.2,
}
_BATCH = 5000

# One edge per (source, target) canonical page. A link matches a page's canonical URL
# as written, or with its trailing slash added or removed.
_EDGES = text(
    """
    SELECT DISTINCT p.id AS source, coalesce(q.duplicate_of_id, q.id) AS target
    FROM pages p
    JOIN crawled_documents cd ON cd.id = p.crawled_document_id
    CROSS JOIN LATERAL unnest(cd.links) AS l(url)
    JOIN pages q ON q.canonical_url IN (l.url, rtrim(l.url, '/'), rtrim(l.url, '/') || '/')
    WHERE p.duplicate_of_id IS NULL
      AND coalesce(q.duplicate_of_id, q.id) <> p.id
    """
)


def pagerank(nodes: Sequence[int], edges: Sequence[tuple[int, int]]) -> dict[int, float]:
    """PageRank over `nodes` (values sum to 1). Edges to unknown nodes are ignored."""
    n = len(nodes)
    if n == 0:
        return {}
    index = {node: i for i, node in enumerate(nodes)}
    out_degree = [0] * n
    incoming: list[list[int]] = [[] for _ in range(n)]
    for source, target in edges:
        s, t = index.get(source), index.get(target)
        if s is None or t is None:
            continue
        out_degree[s] += 1
        incoming[t].append(s)
    rank = [1.0 / n] * n
    for _ in range(MAX_ITERATIONS):
        dangling = sum(rank[i] for i in range(n) if out_degree[i] == 0)
        base = (1.0 - DAMPING) / n + DAMPING * dangling / n
        new = [
            base + DAMPING * sum(rank[s] / out_degree[s] for s in incoming[i]) for i in range(n)
        ]
        change = sum(abs(a - b) for a, b in zip(new, rank, strict=True))
        rank = new
        if change < TOLERANCE:
            break
    return {node: rank[i] for node, i in index.items()}


def _log_scale(value: float, top: float) -> float:
    """0..1 on a log scale, `top` -> 1. `value` is a multiple of the average (1 = average)."""
    if top <= 0 or value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(top))


def freshness(reference: datetime | None, now: datetime) -> float:
    if reference is None:
        return 0.0
    age_days = max(0.0, (now - reference).total_seconds() / 86400)
    return 0.5 ** (age_days / FRESHNESS_HALF_LIFE_DAYS)


def quality(word_count: int, flags: Sequence[str] | None) -> float:
    base = min(1.0, math.log1p(max(word_count, 0)) / math.log1p(QUALITY_FULL_WORDS))
    return max(0.0, min(1.0, base - QUALITY_FLAG_PENALTY * len(flags or [])))


class RankingRepository:
    """Score refresh and ranking features for one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def refresh_scores(self, *, when: datetime | None = None) -> dict[str, int]:
        """Recompute `page_scores` and `domain_stats` link figures. Returns counts.

        Pages that became duplicates lose their scores. Every domain gets a
        `domain_stats` row (zeros when it has no pages).
        """
        now = when or datetime.now(UTC)
        pages = self.session.execute(
            select(
                Page.id,
                Page.domain_id,
                Page.word_count,
                Page.quality_flags,
                Page.published_at,
                Page.last_seen_at,
            ).where(Page.duplicate_of_id.is_(None))
        ).all()
        edges = [(row.source, row.target) for row in self.session.execute(_EDGES)]
        ranks = pagerank([p.id for p in pages], edges)
        n = len(pages)

        domain_of = {p.id: p.domain_id for p in pages}
        inbound: dict[int, int] = {}
        domain_inbound: dict[int, int] = {}
        for source, target in edges:
            if target not in domain_of:
                continue
            inbound[target] = inbound.get(target, 0) + 1
            target_domain = domain_of[target]
            if target_domain is not None and domain_of.get(source) != target_domain:
                domain_inbound[target_domain] = domain_inbound.get(target_domain, 0) + 1

        domain_rank: dict[int, float] = {}
        for page_id, rank in ranks.items():
            domain_id = domain_of[page_id]
            if domain_id is not None:
                domain_rank[domain_id] = domain_rank.get(domain_id, 0.0) + rank
        top_domain = max(domain_rank.values(), default=0.0) * n
        authority = {d: _log_scale(r * n, top_domain) for d, r in domain_rank.items()}
        self._write_domain_figures(domain_inbound, authority, now)

        top_page = max(ranks.values(), default=0.0) * n
        weights = STATIC_RANK_WEIGHTS
        rows = []
        for p in pages:
            pr_scaled = _log_scale(ranks[p.id] * n, top_page)
            fresh = freshness(p.published_at or p.last_seen_at, now)
            qual = quality(p.word_count, p.quality_flags)
            static = (
                weights["pagerank"] * pr_scaled
                + weights["domain_authority"] * authority.get(p.domain_id, 0.0)
                + weights["quality"] * qual
                + weights["freshness"] * fresh
            )
            rows.append(
                {
                    "page_id": p.id,
                    "pagerank": ranks[p.id],
                    "inbound_links": inbound.get(p.id, 0),
                    "freshness_score": fresh,
                    "quality_score": qual,
                    "static_rank": min(1.0, max(0.0, static)),
                    "computed_at": now,
                }
            )
        for start in range(0, len(rows), _BATCH):
            stmt = insert(PageScore).values(rows[start : start + _BATCH])
            self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[PageScore.page_id],
                    set_={
                        col: stmt.excluded[col]
                        for col in (
                            "pagerank",
                            "inbound_links",
                            "freshness_score",
                            "quality_score",
                            "static_rank",
                            "computed_at",
                        )
                    }
                    | {"updated_at": text("now()")},
                )
            )
        removed = self.session.execute(
            delete(PageScore).where(
                PageScore.page_id.in_(select(Page.id).where(Page.duplicate_of_id.is_not(None)))
            )
        ).rowcount
        self.session.expire_all()
        return {"pages": len(rows), "edges": len(edges), "removed": int(removed or 0)}

    def _write_domain_figures(
        self, inbound: dict[int, int], authority: dict[int, float], now: datetime
    ) -> None:
        # Every domain gets a row; refresh_domain_stats fills in its crawl counts.
        self.session.execute(
            text(
                "INSERT INTO domain_stats (domain_id, computed_at) "
                "SELECT id, :now FROM domains ON CONFLICT (domain_id) DO NOTHING"
            ),
            {"now": now},
        )
        self.session.execute(
            update(DomainStats).values(inbound_link_count=0, authority_score=0.0)
        )
        figures = [
            {"d_id": d, "inbound": inbound.get(d, 0), "authority": authority.get(d, 0.0)}
            for d in set(inbound) | set(authority)
        ]
        if figures:
            # Core table, not the ORM entity: an executemany UPDATE keyed on a non-PK column.
            table = DomainStats.__table__
            self.session.execute(
                update(table)
                .where(table.c.domain_id == bindparam("d_id"))
                .values(
                    inbound_link_count=bindparam("inbound", type_=Integer),
                    authority_score=bindparam("authority", type_=Float),
                ),
                figures,
            )

    def ranking_features(self, page_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        """The query-independent features the reranker uses, per canonical page.

        Keys follow the reranker's training columns where they overlap (`freshness`,
        `source_authority`, `content_length`). Scores are None before the first
        `refresh_scores`.
        """
        if not page_ids:
            return {}
        doc = search_documents.c
        rows = self.session.execute(
            select(
                doc.page_id,
                doc.pagerank,
                doc.inbound_links,
                doc.freshness_score,
                doc.quality_score,
                doc.static_rank,
                doc.domain_authority,
                doc.word_count,
                doc.language,
                doc.content_type,
                doc.province_code,
            ).where(doc.page_id.in_(page_ids))
        ).all()
        return {
            row.page_id: {
                "pagerank": row.pagerank,
                "inbound_links": row.inbound_links,
                "freshness": row.freshness_score,
                "quality": row.quality_score,
                "static_rank": row.static_rank,
                "source_authority": row.domain_authority,
                "content_length": row.word_count,
                "language": row.language,
                "content_type": row.content_type,
                "has_geo": row.province_code is not None,
            }
            for row in rows
        }
