"""Load Nepal's administrative geography: 7 provinces, 77 districts, 753 local bodies.

The data lives in ``data/nepal_geography.json``, committed alongside this script so
seeding never depends on the network. Safe to run more than once: every row is
upserted on its ``code``, so re-running refreshes names without creating duplicates.

Usage:  python scripts/seed_geography.py
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pgs_db import make_session_factory
from pgs_db.enums import LocalBodyType
from pgs_db.models import District, LocalBody, Province

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "nepal_geography.json"


def upsert(
    session: Session,
    model: type[Province] | type[District] | type[LocalBody],
    rows: list[dict[str, Any]],
    update: list[str],
) -> None:
    """Insert rows, refreshing `update` columns on any row whose `code` already exists."""
    stmt = insert(model).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[model.code],
            set_={col: getattr(stmt.excluded, col) for col in update},
        )
    )


def main() -> None:
    data: dict[str, list[dict[str, Any]]] = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    # `wards` is stored as `ward_count`; the type string becomes the enum so an unknown
    # value fails here rather than in Postgres.
    local_bodies = [
        {k: v for k, v in row.items() if k != "wards"}
        | {"type": LocalBodyType(row["type"]), "ward_count": row.get("wards")}
        for row in data["local_bodies"]
    ]

    session_factory = make_session_factory()
    with session_factory.begin() as session:
        # Order matters: districts reference provinces.code, local bodies reference districts.code.
        upsert(session, Province, data["provinces"], ["name_en", "name_ne"])
        upsert(session, District, data["districts"], ["province_code", "name_en", "name_ne"])
        upsert(
            session,
            LocalBody,
            local_bodies,
            ["district_code", "type", "name_en", "name_ne", "website", "ward_count"],
        )

    # Devanagari is deliberately kept out of stdout: Windows consoles default to cp1252
    # and would raise UnicodeEncodeError on an otherwise successful seed.
    print(
        f"Seeded {len(data['provinces'])} provinces, "
        f"{len(data['districts'])} districts, "
        f"{len(local_bodies)} local bodies"
    )


if __name__ == "__main__":
    main()
