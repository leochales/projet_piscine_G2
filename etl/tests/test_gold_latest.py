"""La mise à jour de gold.derniere_mesure est testée en SQL :
db/tests/test_gold_derniere_mesure.sql. Ici : lecture de /sensors/status
et enchaînement des deux mises à jour."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from etl import gold_latest


def _site(**sensors: dict[str, Any]) -> dict[str, Any]:
    """Un site de /sensors/status : capteurs ok, sauf ceux passés en argument."""
    names = ["consumption", "electrical", "temperature", "humidity", "network"]
    states: dict[str, Any] = {n: {"status": "ok", "failing_until": None} for n in names}
    states.update(sensors)
    return {"site_name": "Site", "sensors": states, "overall": "ok"}


FAILING = {"status": "failing", "failing_until": "2024-06-15T14:33:05"}


def test_parse_donne_une_ligne_par_capteur_avec_l_heure_en_utc() -> None:
    rows = gold_latest.parse_sensor_status(
        {"SITE001": _site(temperature=FAILING)}, {"SITE001"}
    )

    assert len(rows) == 5
    temperature = next(r for r in rows if r["capteur"] == "temperature")
    assert temperature == {
        "id_site": "SITE001",
        "capteur": "temperature",
        "statut": "failing",
        "en_panne_jusqu_a": datetime(2024, 6, 15, 14, 33, 5, tzinfo=UTC),
    }
    assert all(r["en_panne_jusqu_a"] is None for r in rows if r["statut"] == "ok")


def test_parse_ignore_la_date_de_retablissement_d_un_capteur_ok() -> None:
    ok_with_date = {"status": "ok", "failing_until": "2024-06-15T14:33:05"}
    rows = gold_latest.parse_sensor_status(
        {"SITE001": _site(network=ok_with_date)}, {"SITE001"}
    )

    network = next(r for r in rows if r["capteur"] == "network")
    assert network["en_panne_jusqu_a"] is None


def test_parse_ignore_les_sites_non_declares() -> None:
    payload = {"SITE001": _site(), "SITE999": _site()}
    rows = gold_latest.parse_sensor_status(payload, {"SITE001"})
    assert {r["id_site"] for r in rows} == {"SITE001"}


def test_parse_ignore_un_site_invalide_sans_bloquer_les_autres(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bad = _site(humidity={"status": "cassé", "failing_until": None})
    rows = gold_latest.parse_sensor_status(
        {"SITE001": bad, "SITE002": _site()}, {"SITE001", "SITE002"}
    )

    assert {r["id_site"] for r in rows} == {"SITE002"}
    assert "site=SITE001 ignoré" in caplog.text


def test_parse_refuse_un_capteur_inconnu() -> None:
    site = _site()
    site["sensors"]["pression"] = {"status": "ok", "failing_until": None}
    assert gold_latest.parse_sensor_status({"SITE001": site}, {"SITE001"}) == []


def test_parse_une_reponse_qui_n_est_pas_un_objet_ne_donne_rien() -> None:
    assert gold_latest.parse_sensor_status(["SITE001"], {"SITE001"}) == []


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def execute(self, sql: Any, params: Any = None) -> Any:
        self.calls.append((str(sql), params))
        if "mettre_a_jour_derniere_mesure" in str(sql):
            return SimpleNamespace(scalar_one=lambda: 2)
        if "FROM app.site" in str(sql):
            return [SimpleNamespace(id_site="SITE001", capacite_kw=500)]
        return None


def _fake_engine(conn: FakeConnection) -> Any:
    class FakeEngine:
        @contextmanager
        def begin(self) -> Iterator[FakeConnection]:
            yield conn

    return lambda: FakeEngine()


def test_update_met_a_jour_la_derniere_mesure_puis_les_capteurs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    monkeypatch.setattr(gold_latest, "get_engine", _fake_engine(conn))
    monkeypatch.setattr(
        gold_latest, "get_sensor_status", lambda: {"SITE001": _site(network=FAILING)}
    )

    assert gold_latest.update() == {"sites_updated": 2, "sensors_updated": 5}
    upsert = [params for sql, params in conn.calls if "gold.etat_capteur" in sql]
    assert len(upsert) == 1 and len(upsert[0]) == 5


def test_update_garde_la_derniere_mesure_si_l_api_est_injoignable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    monkeypatch.setattr(gold_latest, "get_engine", _fake_engine(conn))

    def unreachable() -> dict[str, Any]:
        raise requests.ConnectionError("API Mock injoignable")

    monkeypatch.setattr(gold_latest, "get_sensor_status", unreachable)

    assert gold_latest.update() == {"sites_updated": 2, "sensors_updated": 0}
    assert not any("gold.etat_capteur" in sql for sql, _ in conn.calls)
