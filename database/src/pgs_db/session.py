"""Engine and session helpers."""

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_database_url() -> str:
    """Read DATABASE_URL, e.g. postgresql+psycopg://pgs:pgs@localhost:5432/pgs."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see database/.env.example)")
    return url


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def make_engine(database_url: str | None = None) -> Engine:
    """Create a pooled engine. pool_pre_ping drops dead connections automatically.

    Tunable per service through the environment:

    - `DB_POOL_SIZE` (default 5) / `DB_MAX_OVERFLOW` (10): connections per process.
      Keep workers x (size + overflow) under the server's max_connections.
    - `DB_POOL_RECYCLE` (1800 s): replace connections older than this, so load
      balancers and PgBouncer idle timeouts never hand out a dead one.
    - `DB_APPLICATION_NAME`: shows the service in pg_stat_activity (e.g. "pgs-api").
    """
    url = database_url or get_database_url()
    connect_args = {}
    application_name = os.environ.get("DB_APPLICATION_NAME")
    if application_name and url.startswith("postgresql"):
        connect_args["application_name"] = application_name
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=_env_int("DB_POOL_SIZE", 5),
        max_overflow=_env_int("DB_MAX_OVERFLOW", 10),
        pool_recycle=_env_int("DB_POOL_RECYCLE", 1800),
        connect_args=connect_args,
    )


def make_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(database_url), autoflush=False, expire_on_commit=False)


def get_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session; commit on success, roll back on error, always close."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
