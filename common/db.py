"""Connexion PostgreSQL partagée (SQLAlchemy)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from common.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping : évite les erreurs sur une connexion fermée par PostgreSQL
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, fermée à la fin."""
    session_factory = sessionmaker(bind=get_engine())
    with session_factory() as session:
        yield session


def check_database() -> bool:
    """Renvoie True si PostgreSQL répond à un SELECT 1."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
