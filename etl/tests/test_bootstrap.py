from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from etl import api_client, bootstrap
from etl.bootstrap import (
    BOOTSTRAP_DEPTH,
    SAFETY_LAG,
    STEP,
    Window,
    fetch_history,
    plan_windows,
    select_readings,
)

SLOT = datetime(2026, 10, 26, 8, 13, tzinfo=UTC)


def _mesure(site: str, ts: datetime) -> dict[str, Any]:
    """Réponse type de /readings : horodatage en « …Z »."""
    return {
        "site_id": site,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "consumption_kw": 10.0,
    }


def test_amorcage_de_24_h_en_fenetres_de_1000_minutes() -> None:
    windows = plan_windows(SLOT)

    assert windows[0].start == SLOT - BOOTSTRAP_DEPTH
    assert windows[-1].end == SLOT - SAFETY_LAG
    assert [w.limit for w in windows] == [1000, 438]
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

    assert [c["limit"] for c in calls] == [1000, 438]
    assert len(rows) == 1438
    assert rows[-1][0] == SLOT - SAFETY_LAG - STEP


def test_get_readings_history_refuse_une_limite_invalide() -> None:
    with pytest.raises(ValueError, match="limit"):
        api_client.get_readings_history("SITE001", SLOT, SLOT, 1001)
