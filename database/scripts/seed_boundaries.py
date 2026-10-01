"""Load region boundaries into `provinces` / `districts` / `local_bodies.boundary`.

Reads the committed `data/boundaries/*.geojson.gz` (built by `build_boundaries.py`
from Open Knowledge Nepal's CC BY 4.0 data), so it needs no network. Run it after
`seed_geography.py`. Safe to re-run: each run overwrites the shapes.

A local body stored as several shapes (an exclave) is unioned into one MultiPolygon.
Invalid rings are repaired with ST_MakeValid, so spatial queries never error on them.

Usage:  python scripts/seed_boundaries.py
"""

import gzip
import json
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

from pgs_db import make_session_factory

DATA = Path(__file__).resolve().parent.parent / "data" / "boundaries"
LEVELS = (("provinces", "provinces"), ("districts", "districts"), ("local_bodies", "local_bodies"))

_SET_BOUNDARY = text(
    """
    UPDATE {table}
    SET boundary = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(ARRAY(
            SELECT ST_SetSRID(ST_GeomFromGeoJSON(g), 4326) FROM unnest(:geoms) AS g
        ))), 3)),
        updated_at = now()
    WHERE code = :code
    """
)


def load(level_file: str) -> dict[str, list[str]]:
    """code -> the GeoJSON geometries (as strings) of its shapes."""
    with gzip.open(DATA / f"{level_file}.geojson.gz", "rt", encoding="utf-8") as fh:
        collection: dict[str, Any] = json.load(fh)
    shapes: dict[str, list[str]] = {}
    for feature in collection["features"]:
        shapes.setdefault(feature["properties"]["code"], []).append(
            json.dumps(feature["geometry"])
        )
    return shapes


def main() -> None:
    session_factory = make_session_factory()
    with session_factory.begin() as session:
        for table, level_file in LEVELS:
            stmt = text(_SET_BOUNDARY.text.format(table=table)).bindparams(
                bindparam("geoms", type_=ARRAY(Text))
            )
            shapes = load(level_file)
            updated = 0
            for code, geoms in shapes.items():
                updated += session.execute(stmt, {"code": code, "geoms": geoms}).rowcount
            missing = session.scalar(text(f"SELECT count(*) FROM {table} WHERE boundary IS NULL"))
            if updated != len(shapes) or missing:
                raise SystemExit(
                    f"{table}: {len(shapes)} codes in the file, {updated} rows updated, "
                    f"{missing} rows still without a boundary -- run seed_geography.py first"
                )
            print(f"{table}: {updated} boundaries loaded")


if __name__ == "__main__":
    main()
