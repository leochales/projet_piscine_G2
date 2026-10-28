"""Les règles de détection sont testées en SQL : db/tests/test_gold_alertes.sql."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from etl import gold_alerts


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


def _alerte(capteur: str | None, en_cours: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id_site="SITE001",
        type="sensor" if capteur else "threshold",
        capteur=capteur,
        debut=datetime(2026, 10, 26, 10, 0, tzinfo=UTC),
        en_cours=en_cours,
    )


def test_detect_appelle_la_fonction_sql_et_compte_les_alertes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection([_alerte(None, True), _alerte("electrical", False)])
    monkeypatch.setattr(gold_alerts, "get_engine", _fake_engine(conn))

    assert gold_alerts.detect() == {"alerts_written": 2, "in_progress": 1}
    assert "gold.detecter_alertes()" in conn.sql[0]


def test_detect_sans_alerte_n_ecrit_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold_alerts, "get_engine", _fake_engine(FakeConnection([])))
    assert gold_alerts.detect() == {"alerts_written": 0, "in_progress": 0}
