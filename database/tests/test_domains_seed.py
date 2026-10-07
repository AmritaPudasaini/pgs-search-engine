"""data/domains.json (the websites to crawl) and scripts/seed_domains.py."""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pgs_db.enums import DomainCategory, DomainPriority, DomainStatus
from pgs_db.models import Domain, LocalBody

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = json.loads((ROOT / "data" / "domains.json").read_text(encoding="utf-8"))["domains"]
GEOGRAPHY = json.loads((ROOT / "data" / "nepal_geography.json").read_text(encoding="utf-8"))


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rows_fit_the_domains_table() -> None:
    names = [row["domain"] for row in DOMAINS]
    assert len(names) == len(set(names)), "a website appears twice"
    for row in DOMAINS:
        assert row["domain"] == row["domain"].lower() and not row["domain"].startswith("www.")
        assert len(row["domain"]) <= 255
        DomainCategory(row["category"])
        DomainStatus(row["status"])
        DomainPriority(row["priority"])
        assert row["rate_limit_per_sec"] > 0


def test_every_local_body_website_is_geo_linked() -> None:
    codes = {lb["code"] for lb in GEOGRAPHY["local_bodies"]}
    linked = {row["local_body_code"] for row in DOMAINS if row["local_body_code"]}
    assert linked <= codes, "a domain points at a local body that does not exist"
    assert linked == codes, "a local body's website is missing from domains.json"
    for row in DOMAINS:
        if row["local_body_code"]:
            assert row["category"] == "GOVERNMENT" and row["website_name"]


@pytest.mark.skipif(
    not (ROOT.parent / "scraper" / "configs" / "seeds.example.txt").exists(),
    reason="the scraper's seed list is not checked out next to database/",
)
def test_file_is_up_to_date_with_its_sources() -> None:
    assert _script("build_domains").build() == DOMAINS, "run python scripts/build_domains.py"


def test_seed_links_domains_to_their_local_body(session: Session) -> None:
    seed = _script("seed_domains")
    ids = dict(session.execute(select(LocalBody.code, LocalBody.id)).tuples().all())
    if not ids:
        pytest.skip("geography is not seeded")
    rows = seed.rows_from_file(ids)
    assert len(rows) == len(DOMAINS)
    pokhara = next(r for r in rows if r["domain"] == "pokharamun.gov.np")
    assert pokhara["local_body_id"] == ids["MUN414"]
    # The seeded database (db-migrate) holds them, linked.
    if session.scalar(select(func.count()).select_from(Domain)):
        linked = session.scalar(
            select(LocalBody.code).join(Domain, Domain.local_body_id == LocalBody.id).where(
                Domain.domain == "pokharamun.gov.np"
            )
        )
        assert linked == "MUN414"
