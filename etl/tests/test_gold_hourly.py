"""Le calcul lui-même est testé en SQL : db/tests/test_gold_horaire.sql."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from etl import gold_hourly


class FakeConnection:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.sql: list[str] = []

    def execute(self, sql: Any) -> list[SimpleNamespace]:
        self.sql.append(str(sql))
        return self.rows


def _fake_engine(conn: FakeConnection) -> Any:
    class FakeEngine:
        @contextmanager
        def begin(self) -> Iterator[FakeConnection]:
            yield conn

    return FakeEngine


def test_aggregate_appelle_la_fonction_sql_et_compte_les_heures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(
        [
            SimpleNamespace(id_site="SITE001", heures=2),
            SimpleNamespace(id_site="SITE002", heures=25),
        ]
    )
    monkeypatch.setattr(gold_hourly, "get_engine", _fake_engine(conn))

    assert gold_hourly.aggregate() == {"sites": 2, "hours_written": 27}
    assert "gold.calculer_consommation_horaire()" in conn.sql[0]


def test_aggregate_sans_silver_n_ecrit_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold_hourly, "get_engine", _fake_engine(FakeConnection([])))
    assert gold_hourly.aggregate() == {"sites": 0, "hours_written": 0}
