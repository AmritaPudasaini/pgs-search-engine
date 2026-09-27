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


def make_engine(database_url: str | None = None) -> Engine:
    """Create a pooled engine. pool_pre_ping drops dead connections automatically."""
    return create_engine(database_url or get_database_url(), pool_pre_ping=True)


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
