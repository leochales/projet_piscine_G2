import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from etl import collect
from etl.collect import (
    MAX_CLOCK_SKEW,
    ReadingRejected,
    check_sites_consistency,
    reading_slot,
)
from etl.grid import floor_to_step
from etl.schemas import SiteInfo

# Horloge locale ; l'horloge de l'API Mock retarde d'une trentaine de secondes
NOW = datetime(2026, 10, 26, 8, 13, 5, tzinfo=UTC)
# Minute du passage (horloge locale), et non celle de l'horodatage de l'API
SLOT = datetime(2026, 10, 26, 8, 13, tzinfo=UTC)


def _mesure(site: str, ts: str = "2026-10-26T08:12:39.385024") -> dict[str, Any]:
    """Réponse type de /current : horodatage sans fuseau, à la microseconde."""
    return {
        "site_id": site,
        "timestamp": ts,
        "consumption_kw": 10.0,
        "data_quality": "good",
    }


def test_floor_to_step_tronque_a_la_minute() -> None:
    ts = datetime(2026, 10, 22, 13, 1, 19, 285952, tzinfo=UTC)
    assert floor_to_step(ts) == datetime(2026, 10, 22, 13, 1, tzinfo=UTC)


# --- reading_slot -------------------------------------------------------------


def test_reading_slot_range_la_mesure_current_sur_la_minute_utc() -> None:
    assert reading_slot("SITE001", _mesure("SITE001"), NOW) == SLOT


def test_reading_slot_ne_depend_pas_du_retard_de_l_api() -> None:
    # Démarrage à :00.5 puis à :01.5 : l'horodatage de l'API (≈ −31 s) passe
    # d'une minute à l'autre, la clé reste la minute du passage
    for t, ts in [
        (datetime(2026, 10, 26, 8, 13, 0, 500000, tzinfo=UTC), "2026-10-26T08:12:29.6"),
        (datetime(2026, 10, 26, 8, 14, 1, 500000, tzinfo=UTC), "2026-10-26T08:13:30.6"),
    ]:
        assert reading_slot("SITE001", _mesure("SITE001", ts), t) == floor_to_step(t)


def test_reading_slot_rejette_la_mesure_d_un_autre_site() -> None:
    with pytest.raises(ReadingRejected, match="autre site"):
        reading_slot("SITE001", _mesure("SITE002"), NOW)


def test_reading_slot_rejette_un_horodatage_trop_ancien() -> None:
    trop_vieux = (NOW - MAX_CLOCK_SKEW - timedelta(seconds=1)).replace(tzinfo=None)
    with pytest.raises(ReadingRejected, match="trop loin"):
        reading_slot("SITE001", _mesure("SITE001", trop_vieux.isoformat()), NOW)


def test_reading_slot_accepte_un_retard_dans_la_tolerance() -> None:
    limite = (NOW - MAX_CLOCK_SKEW).replace(tzinfo=None)
    slot = reading_slot("SITE001", _mesure("SITE001", limite.isoformat()), NOW)
    assert slot == floor_to_step(NOW)


def test_reading_slot_rejette_un_payload_sans_horodatage() -> None:
    with pytest.raises(ReadingRejected, match="clé valide"):
        reading_slot("SITE001", {"site_id": "SITE001", "consumption_kw": 1.0}, NOW)


# --- Cohérence des sites ------------------------------------------------------


def _site(site_id: str, capacity: float) -> SiteInfo:
    return SiteInfo(
        site_id=site_id,
        site_type="office",
        site_name=site_id,
        location="France",
        capacity_kw=capacity,
        status="active",
    )


def test_coherence_des_sites_avec_l_api_mock() -> None:
    declared = {"SITE001": 200.0, "SITE002": 1000.0, "SITE009": 50.0}
    mock = [_site("SITE001", 200.0), _site("SITE002", 900.0), _site("SITE003", 800)]

    issues = check_sites_consistency(declared, mock)

    assert issues == [
        "site SITE003 présent dans l'API Mock mais non déclaré",
        "site SITE009 déclaré mais absent de l'API Mock",
        "site SITE002 : capacité 1000.0 kW en base, 900.0 kW dans l'API Mock",
    ]


def test_aucun_ecart_quand_tout_concorde() -> None:
    assert check_sites_consistency({"SITE001": 200.0}, [_site("SITE001", 200)]) == []


# --- Orchestration (base et API remplacées) ---------------------------------


class FakeEngine:
    @contextmanager
    def connect(self) -> Iterator[None]:
        yield None

    begin = connect


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "declared": {"SITE001": 200.0, "SITE002": 1000.0, "SITE003": 800.0},
        "calls": [],
        "inserted": [],
    }

    def get_current_reading(site_id: str) -> dict[str, Any]:
        state["calls"].append(site_id)
        return _mesure(site_id)

    def insert_bronze(_: Any, id_site: str, ts: datetime, payload: Any) -> bool:
        state["inserted"].append((id_site, ts, payload))
        return True

    monkeypatch.setattr(collect, "get_engine", FakeEngine)
    monkeypatch.setattr(collect, "load_declared_sites", lambda _: state["declared"])
    monkeypatch.setattr(collect, "log_stale_sites", lambda *_: None)
    monkeypatch.setattr(collect, "get_sites", list)
    monkeypatch.setattr(collect, "get_current_reading", get_current_reading)
    monkeypatch.setattr(collect, "insert_bronze", insert_bronze)
    return state


def test_collect_appelle_current_une_fois_par_site_declare(
    fake_db: dict[str, Any],
) -> None:
    collect.collect(NOW)
    assert sorted(fake_db["calls"]) == ["SITE001", "SITE002", "SITE003"]


def test_collect_additionne_les_insertions(fake_db: dict[str, Any]) -> None:
    assert collect.collect(NOW) == {
        "sites": 3,
        "readings_inserted": 3,
        "sites_in_error": 0,
    }


def test_la_collecte_n_amorce_jamais(fake_db: dict[str, Any]) -> None:
    # L'amorçage /readings est une commande à part (etl.bootstrap) : la
    # collecte minute ne l'attend ni ne le déclenche
    assert not hasattr(collect, "fetch_history")
    assert collect.collect(NOW)["readings_inserted"] == 3


def test_une_erreur_inattendue_sur_un_site_n_arrete_pas_les_autres(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def get_current_reading(site_id: str) -> dict[str, Any]:
        if site_id == "SITE001":
            raise KeyError("réponse imprévue")
        return _mesure(site_id)

    monkeypatch.setattr(collect, "get_current_reading", get_current_reading)

    assert collect.collect(NOW) == {
        "sites": 3,
        "readings_inserted": 2,
        "sites_in_error": 1,
    }


def test_une_erreur_inattendue_du_controle_des_sites_est_loguee(
    fake_db: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def get_sites() -> list[SiteInfo]:
        raise KeyError("réponse imprévue")

    monkeypatch.setattr(collect, "get_sites", get_sites)

    assert collect.collect(NOW)["readings_inserted"] == 3
    assert "contrôle des sites : erreur inattendue" in caplog.text


def test_un_site_en_echec_api_ou_rejete_n_arrete_pas_les_autres(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def get_current_reading(site_id: str) -> dict[str, Any]:
        if site_id == "SITE001":
            raise requests.ConnectionError("API injoignable")
        if site_id == "SITE002":
            return _mesure("SITE999")  # mesure rejetée : autre site
        return _mesure(site_id)

    monkeypatch.setattr(collect, "get_current_reading", get_current_reading)

    assert collect.collect(NOW) == {
        "sites": 3,
        "readings_inserted": 1,
        "sites_in_error": 2,
    }
    assert [i[0] for i in fake_db["inserted"]] == ["SITE003"]


def test_tous_les_sites_en_echec_sort_en_1(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def get_current_reading(site_id: str) -> dict[str, Any]:
        if site_id == "SITE001":
            raise requests.ConnectionError("API injoignable")
        return _mesure(site_id, "2020-01-01T00:00:00")  # trop ancienne

    monkeypatch.setattr(collect, "get_current_reading", get_current_reading)
    with pytest.raises(SystemExit) as exc:
        collect.collect(NOW)
    assert exc.value.code == collect.EXIT_ALL_SITES_FAILED


def test_aucun_site_declare_sort_en_2(fake_db: dict[str, Any]) -> None:
    fake_db["declared"] = {}
    with pytest.raises(SystemExit) as exc:
        collect.collect(NOW)
    assert exc.value.code == collect.EXIT_NO_DECLARED_SITE
    assert fake_db["calls"] == []


def test_collect_site_insere_la_minute_arrondie_et_le_payload_brut(
    fake_db: dict[str, Any],
) -> None:
    mesure = _mesure("SITE001")
    copie = dict(mesure)

    assert collect.collect_site("SITE001", mesure, NOW) == 1

    [(id_site, ts, payload)] = fake_db["inserted"]
    assert (id_site, ts) == ("SITE001", SLOT)
    assert payload is mesure  # payload transmis tel quel…
    assert payload == copie  # …et non modifié


def test_collect_site_renvoie_0_si_la_minute_est_deja_collectee(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "insert_bronze", lambda *_: False)
    assert collect.collect_site("SITE001", _mesure("SITE001"), NOW) == 0


# --- Sites rassis (requête remplacée) ----------------------------------------


class _StaleConn:
    """Connexion dont execute(...) renvoie les sites rassis (site, retard)."""

    def __init__(self, rows: list[tuple[str, timedelta | None]]) -> None:
        self.rows = rows
        self.params: dict[str, Any] = {}

    def execute(self, _: Any, params: dict[str, Any]) -> list[Any]:
        self.params = params
        return [SimpleNamespace(id_site=s, lag=lag) for s, lag in self.rows]


def test_site_rassis_et_site_jamais_collecte_signales(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = _StaleConn([("SITE001", timedelta(minutes=42)), ("SITE-TEST", None)])
    with caplog.at_level(logging.WARNING, logger=collect.__name__):
        collect.log_stale_sites(conn, ["SITE001", "SITE002", "SITE-TEST"])  # type: ignore[arg-type]

    assert conn.params == {
        "ids": ["SITE001", "SITE002", "SITE-TEST"],
        "threshold": collect.STALE_THRESHOLD,
    }
    assert [r.getMessage() for r in caplog.records] == [
        "site SITE001 : dernière mesure il y a 0:42:00",
        "site SITE-TEST : aucune mesure en bronze",
    ]
