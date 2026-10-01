"""Postgres connection pool."""
from contextlib import contextmanager

from psycopg2.pool import ThreadedConnectionPool

from .config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_POOL_MAX,
    POSTGRES_POOL_MIN,
    POSTGRES_PORT,
    POSTGRES_USER,
)

_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            POSTGRES_POOL_MIN, POSTGRES_POOL_MAX,
            host=POSTGRES_HOST, port=POSTGRES_PORT, dbname=POSTGRES_DB,
            user=POSTGRES_USER, password=POSTGRES_PASSWORD,
        )
    return _pool


@contextmanager
def get_connection():
    """Yield a pooled connection. Commits on success, rolls back on error."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None