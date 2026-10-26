from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
import requests

from etl import api_client, bootstrap
from etl.bootstrap import (
    BOOTSTRAP_DEPTH,
    SAFETY_LAG,
    SOURCE_BOOTSTRAP,
    SOURCE_KEY,
    Window,
    fetch_history,
    plan_windows,
    select_readings,
)
from etl.grid import STEP

SLOT = datetime(2026, 10, 26, 8, 13, tzinfo=UTC)
NOW = SLOT + timedelta(seconds=5)


def _mesure(site: str, ts: datetime) -> dict[str, Any]:
    """Réponse type de /readings : horodatage en « …Z »."""
    return {
        "site_id": site,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "consumption_kw": 10.0,
    }


def test_amorcage_de_7_jours_en_fenetres_de_1000_minutes() -> None:
    windows = plan_windows(SLOT)

    assert windows[0].start == SLOT - BOOTSTRAP_DEPTH
    assert windows[-1].end == SLOT - SAFETY_LAG
    assert [w.limit for w in windows] == [1000] * 10 + [78]
    # fenêtres contiguës, pas de 60 s
    for a, b in pairwise(windows):
        assert a.end == b.start
    for w in windows:
        assert (w.end - w.start) / w.limit == STEP


def test_select_readings_garde_les_points_du_site_sur_la_grille() -> None:
    w = Window(start=SLOT, end=SLOT + 3 * STEP, limit=3)
    readings = [
        _mesure("SITE001", SLOT),
        _mesure("SITE001", SLOT + STEP + timedelta(seconds=30)),  # hors grille
        _mesure("SITE002", SLOT + 2 * STEP),  # autre site
        _mesure("SITE001", SLOT + 3 * STEP),  # fin exclue
        {"site_id": "SITE001"},  # sans horodatage
        _mesure("SITE001", SLOT + 2 * STEP),
    ]

    kept = select_readings("SITE001", w, readings)

    assert [ts for ts, _ in kept] == [SLOT, SLOT + 2 * STEP]
    assert kept[0][1] is readings[0]  # payload conservé tel quel


def test_fetch_history_demande_chaque_fenetre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def get_readings_history(**params: Any) -> list[dict[str, Any]]:
        calls.append(params)
        return [
            _mesure("SITE001", params["start_time"] + k * STEP)
            for k in range(params["limit"])
        ]

    monkeypatch.setattr(bootstrap, "get_readings_history", get_readings_history)

    rows = fetch_history("SITE001", SLOT)

    assert [c["limit"] for c in calls] == [1000] * 10 + [78]
    assert len(rows) == 7 * 24 * 60 - 2
    assert rows[-1][0] == SLOT - SAFETY_LAG - STEP
    # payload brut conservé, avec le marqueur d'amorçage en plus
    assert all(payload[SOURCE_KEY] == SOURCE_BOOTSTRAP for _, payload in rows)
    assert rows[0][1]["consumption_kw"] == 10.0


def test_get_readings_history_refuse_une_limite_invalide() -> None:
    with pytest.raises(ValueError, match="limit"):
        api_client.get_readings_history("SITE001", SLOT, SLOT, 1001)


# --- Orchestration (base et API remplacées) ---------------------------------


class FakeEngine:
    @contextmanager
    def connect(self) -> Iterator[None]:
        yield None

    begin = connect


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"todo": ["SITE001", "SITE002"], "inserted": {}}

    def insert_history(_: Any, id_site: str, rows: list[Any]) -> int:
        state["inserted"][id_site] = rows
        return len(rows)

    monkeypatch.setattr(bootstrap, "get_engine", FakeEngine)
    monkeypatch.setattr(
        bootstrap, "load_declared_sites", lambda _: {"SITE001": 1, "SITE002": 1}
    )
    monkeypatch.setattr(bootstrap, "sites_to_bootstrap", lambda *_: state["todo"])
    monkeypatch.setattr(
        bootstrap, "fetch_history", lambda site, slot: [(slot, {"site_id": site})]
    )
    monkeypatch.setattr(bootstrap, "insert_history", insert_history)
    return state


def test_rien_a_amorcer_quand_tous_les_sites_ont_des_mesures(
    fake_db: dict[str, Any],
) -> None:
    fake_db["todo"] = []
    assert bootstrap.bootstrap(NOW)["sites"] == 0
    assert fake_db["inserted"] == {}


def test_amorce_chaque_site_sans_mesure(fake_db: dict[str, Any]) -> None:
    assert bootstrap.bootstrap(NOW) == {
        "sites": 2,
        "readings_inserted": 2,
        "sites_in_error": 0,
    }
    assert sorted(fake_db["inserted"]) == ["SITE001", "SITE002"]


def test_un_site_en_echec_n_empeche_pas_les_autres(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch_history(site: str, slot: datetime) -> list[Any]:
        if site == "SITE001":
            raise requests.HTTPError("400 Bad Request")
        return [(slot, {"site_id": site})]

    monkeypatch.setattr(bootstrap, "fetch_history", fetch_history)

    assert bootstrap.bootstrap(NOW)["sites_in_error"] == 1
    assert list(fake_db["inserted"]) == ["SITE002"]


def test_tous_les_sites_en_echec_sort_en_1(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch_history(site: str, slot: datetime) -> list[Any]:
        raise requests.ConnectionError("API injoignable")

    monkeypatch.setattr(bootstrap, "fetch_history", fetch_history)
    with pytest.raises(SystemExit) as exc:
        bootstrap.bootstrap(NOW)
    assert exc.value.code == bootstrap.EXIT_ALL_SITES_FAILED
