from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
