"""Load the websites to crawl into `domains` from data/domains.json.

Run after seed_geography.py (it resolves each row's `local_body_code` to
`local_bodies.id`: the domain's geolocation). Safe to run on every start: a new
website is inserted; an existing one keeps what the admin or the app set (status,
priority, category, rate limit, a manual local-body link) and only gets
`local_body_id` / `website_name` filled where they are still empty.

The JSON is built by scripts/build_domains.py from the scraper's seed list and the
local bodies' websites; the scraper itself never writes domains at startup.

Usage:  python scripts/seed_domains.py
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from pgs_db import make_session_factory
from pgs_db.enums import DomainCategory, DomainPriority, DomainStatus
from pgs_db.models import Domain, LocalBody

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "domains.json"
BATCH = 1000


def rows_from_file(local_body_ids: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for row in json.loads(DATA_FILE.read_text(encoding="utf-8"))["domains"]:
        code = row["local_body_code"]
        if code is not None and code not in local_body_ids:
            raise ValueError(
                f"{row['domain']}: unknown local body {code} (run seed_geography.py first)"
            )
        rows.append(
            {
                "domain": row["domain"],
                "website_name": row["website_name"],
                # The enums fail here, on a bad value, rather than in a CHECK constraint.
                "category": DomainCategory(row["category"]),
                "status": DomainStatus(row["status"]),
                "priority": DomainPriority(row["priority"]),
                "rate_limit_per_sec": row["rate_limit_per_sec"],
                "local_body_id": local_body_ids.get(code) if code else None,
            }
        )
    return rows


def main() -> None:
    session_factory = make_session_factory()
    with session_factory.begin() as session:
        local_body_ids = dict(session.execute(select(LocalBody.code, LocalBody.id)).tuples().all())
        rows = rows_from_file(local_body_ids)
        before = session.scalar(select(func.count()).select_from(Domain)) or 0
        for start in range(0, len(rows), BATCH):
            stmt = insert(Domain).values(rows[start : start + BATCH])
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Domain.domain],
                    set_={
                        "local_body_id": func.coalesce(
                            Domain.local_body_id, stmt.excluded.local_body_id
                        ),
                        "website_name": func.coalesce(
                            Domain.website_name, stmt.excluded.website_name
                        ),
                    },
                )
            )
        after = session.scalar(select(func.count()).select_from(Domain)) or 0
        linked = session.scalar(
            select(func.count()).select_from(Domain).where(Domain.local_body_id.is_not(None))
        )
    print(f"Seeded domains: {after - before} new, {after} total, {linked} linked to a local body")


if __name__ == "__main__":
    main()
