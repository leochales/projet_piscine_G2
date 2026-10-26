"""Les règles et le calcul sont testés en SQL : db/tests/test_gold_recommandations.sql."""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from etl import recommandations


class FakeResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class FakeConnection:
    def __init__(self, nb: int) -> None:
        self.nb = nb
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: Any, params: dict[str, Any]) -> FakeResult:
        self.calls.append((str(sql), params))
        return FakeResult(self.nb)


def _fake_engine(conn: FakeConnection) -> Any:
    class FakeEngine:
        @contextmanager
        def begin(self) -> Iterator[FakeConnection]:
            yield conn

    return FakeEngine


def test_generate_appelle_la_fonction_sql_avec_le_prix_du_kwh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIX_KWH_EUR", "0.2")
    recommandations.get_settings.cache_clear()
    conn = FakeConnection(3)
    monkeypatch.setattr(recommandations, "get_engine", _fake_engine(conn))

    assert recommandations.generate() == 3
    sql, params = conn.calls[0]
    assert "gold.generer_recommandations(:prix)" in sql
    assert params == {"prix": Decimal("0.2")}
    recommandations.get_settings.cache_clear()


def test_generate_sans_alerte_ne_cree_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recommandations, "get_engine", _fake_engine(FakeConnection(0)))
    assert recommandations.generate() == 0
