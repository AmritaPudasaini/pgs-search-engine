"""The Go scraper defines no schema: sqlc generates its models from
sql/scraper_schema.sql, which scripts/export_scraper_schema.py generates from the
pgs_db models. These tests keep that chain honest: the file must be up to date with
the models, and the models must match what the migrations actually created."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from pgs_db.base import Base

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_scraper_schema.py"
_spec = importlib.util.spec_from_file_location("export_scraper_schema", _SCRIPT)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

# The compiled SQLAlchemy type -> information_schema.columns.data_type.
_DATA_TYPES = {
    "TEXT": "text",
    "INTEGER": "integer",
    "BIGINT": "bigint",
    "FLOAT": "double precision",
    "JSONB": "jsonb",
    "TIMESTAMP WITH TIME ZONE": "timestamp with time zone",
}


def _model_type(column) -> str:
    compiled = column.type.compile(dialect=postgresql.dialect())
    if compiled.endswith("[]"):
        return "ARRAY"
    if compiled.startswith("VARCHAR"):
        return "character varying" + compiled[len("VARCHAR"):]
    return _DATA_TYPES[compiled]


def test_generated_schema_is_up_to_date() -> None:
    assert export.OUTPUT.read_text(encoding="utf-8") == export.render(), (
        "sql/scraper_schema.sql is out of date: run python scripts/export_scraper_schema.py "
        "and `make sqlc` in scraper/"
    )


@pytest.mark.parametrize("table", export.SCRAPER_TABLES)
def test_models_match_the_migrated_table(session: Session, table: str) -> None:
    rows = session.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    migrated = {}
    for name, data_type, max_length, is_nullable in rows:
        if data_type == "character varying" and max_length:
            data_type = f"character varying({max_length})"
        migrated[name] = (data_type, is_nullable == "YES")
    modelled = {c.name: (_model_type(c), bool(c.nullable)) for c in Base.metadata.tables[table].c}
    assert modelled == migrated, (
        f"the pgs_db model of {table} differs from the migrated database: "
        "fix the model or add a migration"
    )
