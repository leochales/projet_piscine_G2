from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

from common import db


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Remplace PostgreSQL par une base SQLite en mémoire."""
    sqlite = create_engine("sqlite://")
    monkeypatch.setattr(db, "get_engine", lambda: sqlite)
    yield sqlite
    sqlite.dispose()


def test_check_database_vrai_quand_la_base_repond(engine: Engine) -> None:
    assert db.check_database() is True


def test_check_database_faux_quand_la_base_est_injoignable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Port 1 : connexion refusée immédiatement, sans attendre de délai réseau
    unreachable = create_engine("postgresql+psycopg://u:p@127.0.0.1:1/x")
    monkeypatch.setattr(db, "get_engine", lambda: unreachable)
    assert db.check_database() is False


def test_get_session_fournit_une_session_puis_la_ferme(engine: Engine) -> None:
    sessions = db.get_session()
    session = next(sessions)
    assert session.execute(text("SELECT 1")).scalar() == 1
    sessions.close()  # fin de la requête : le with de get_session ferme la session
    assert not session.in_transaction()


def test_get_engine_utilise_l_url_de_la_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "d")
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    try:
        assert (
            db.get_engine()
            .url.render_as_string(hide_password=False)
            .endswith("u:p@localhost:5432/d")
        )
    finally:
        db.get_settings.cache_clear()
        db.get_engine.cache_clear()
