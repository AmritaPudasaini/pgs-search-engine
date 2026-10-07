"""Tests run against a real Postgres at DATABASE_URL (after `alembic upgrade head`).
Each test runs inside a transaction that is rolled back."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from pgs_db import make_engine

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set", allow_module_level=True)


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = make_engine()
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()
