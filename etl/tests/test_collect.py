from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests

from etl import api_client, collect
from etl.collect import (
    DEFAULT_BACKFILL,
    MAX_BACKFILL,
    STEP,
    Window,
    check_sites_consistency,
    floor_to_step,
    plan_windows,
    select_readings,
)
from etl.schemas import SiteInfo

# Horloge locale ; la dernière minute collectable est 12:28 (now − 2 min)
NOW = datetime(2026, 10, 22, 12, 30, 45, tzinfo=UTC)
LAST = datetime(2026, 10, 22, 12, 28, tzinfo=UTC)


def test_floor_to_step_tronque_a_la_minute() -> None:
    ts = datetime(2026, 10, 22, 13, 1, 19, 285952, tzinfo=UTC)
    assert floor_to_step(ts) == datetime(2026, 10, 22, 13, 1, tzinfo=UTC)


def test_sans_watermark_remonte_24_h_en_fenetres_de_1000_minutes() -> None:
    windows = plan_windows(None, NOW)

    assert windows[0].start == LAST - DEFAULT_BACKFILL
    assert [w.limit for w in windows] == [1000, 441]  # 24 h + 1 = 1441 minutes
    assert windows[0].end == windows[1].start  # fenêtres jointives
    assert windows[-1].end == LAST + STEP  # borne de fin exclue


def test_chaque_fenetre_donne_un_pas_de_60_s() -> None:
    # L'API calcule le pas comme (end − start) / limit
    for w in plan_windows(None, NOW):
        assert (w.end - w.start) / w.limit == STEP
        assert w.start.second == 0 and w.start.microsecond == 0


def test_watermark_aligne_repart_a_la_minute_suivante() -> None:
    windows = plan_windows(datetime(2026, 10, 22, 12, 20, tzinfo=UTC), NOW)
    assert windows == [
        Window(
            start=datetime(2026, 10, 22, 12, 21, tzinfo=UTC),
            end=LAST + STEP,
            limit=8,
        )
    ]


def test_watermark_hors_grille_de_l_ancienne_collecte() -> None:
    watermark = datetime(2026, 10, 22, 12, 20, 19, 285952, tzinfo=UTC)
    assert plan_windows(watermark, NOW)[0].start == datetime(
        2026, 10, 22, 12, 21, tzinfo=UTC
    )


def test_rien_a_collecter_quand_le_site_est_a_jour() -> None:
    assert plan_windows(LAST, NOW) == []


def test_rattrapage_plafonne_apres_une_longue_coupure() -> None:
    windows = plan_windows(NOW - timedelta(days=30), NOW)
    assert windows[0].start == LAST - MAX_BACKFILL
    assert sum(w.limit for w in windows) == MAX_BACKFILL // STEP + 1


def _mesure(site: str, ts: str) -> dict[str, Any]:
    return {"site_id": site, "timestamp": ts, "consumption_kw": 10.0}


def test_select_readings_garde_les_points_de_la_grille() -> None:
    window = Window(
        start=datetime(2026, 10, 21, tzinfo=UTC),
        end=datetime(2026, 10, 21, 0, 3, tzinfo=UTC),
        limit=3,
    )
    readings = [
        _mesure("SITE001", "2026-10-21T00:00:00Z"),
        _mesure("SITE001", "2026-10-21T00:01:00Z"),
        _mesure("SITE001", "2026-10-21T00:01:30Z"),  # hors grille
        _mesure("SITE002", "2026-10-21T00:02:00Z"),  # autre site
        _mesure("SITE001", "2026-10-21T00:03:00Z"),  # borne de fin exclue
        {"site_id": "SITE001"},  # sans horodatage
    ]

    kept, rejected = select_readings("SITE001", window, readings)

    assert [ts.minute for ts, _ in kept] == [0, 1]
    assert kept[0][1] is readings[0]  # payload conservé tel quel
    assert rejected == 4


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
    state: dict[str, Any] = {"declared": {"SITE001": 200.0, "SITE002": 1000.0}}
    monkeypatch.setattr(collect, "get_engine", FakeEngine)
    monkeypatch.setattr(collect, "load_declared_sites", lambda _: state["declared"])
    monkeypatch.setattr(
        collect, "get_watermarks", lambda _, ids: dict.fromkeys(ids, LAST)
    )
    monkeypatch.setattr(collect, "log_stale_sites", lambda *_: None)
    monkeypatch.setattr(collect, "get_sites", list)
    return state


def test_collect_additionne_les_insertions(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "collect_site", lambda *_: 5)
    assert collect.collect(NOW) == {
        "sites": 2,
        "readings_inserted": 10,
        "sites_in_error": 0,
    }


def test_un_site_en_echec_n_arrete_pas_les_autres(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def collect_site(id_site: str, *_: Any) -> int:
        if id_site == "SITE001":
            raise requests.ConnectionError("API injoignable")
        return 3

    monkeypatch.setattr(collect, "collect_site", collect_site)
    assert collect.collect(NOW)["sites_in_error"] == 1


def test_tous_les_sites_en_echec_sort_en_1(
    fake_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def collect_site(*_: Any) -> int:
        raise requests.ConnectionError("API injoignable")

    monkeypatch.setattr(collect, "collect_site", collect_site)
    with pytest.raises(SystemExit) as exc:
        collect.collect(NOW)
    assert exc.value.code == collect.EXIT_ALL_SITES_FAILED


def test_aucun_site_declare_sort_en_2(fake_db: dict[str, Any]) -> None:
    fake_db["declared"] = {}
    with pytest.raises(SystemExit) as exc:
        collect.collect(NOW)
    assert exc.value.code == collect.EXIT_NO_DECLARED_SITE


def test_collect_site_demande_chaque_fenetre_et_insere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def get_readings_history(**params: Any) -> list[dict[str, Any]]:
        calls.append(params)
        start = params["start_time"]
        return [
            _mesure("SITE001", (start + k * STEP).isoformat())
            for k in range(params["limit"])
        ]

    inserted: list[int] = []

    def insert_bronze(_: Any, __: str, rows: list[Any]) -> int:
        inserted.append(len(rows))
        return len(rows)

    monkeypatch.setattr(collect, "get_readings_history", get_readings_history)
    monkeypatch.setattr(collect, "get_engine", FakeEngine)
    monkeypatch.setattr(collect, "insert_bronze", insert_bronze)

    collect.collect_site("SITE001", None, NOW)

    assert [c["limit"] for c in calls] == [1000, 441]
    assert inserted == [1000, 441]


def test_get_readings_history_refuse_une_limite_invalide() -> None:
    with pytest.raises(ValueError, match="limit"):
        api_client.get_readings_history("SITE001", NOW, NOW, 1001)
