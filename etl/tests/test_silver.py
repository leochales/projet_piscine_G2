from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from etl.collect import STEP, floor_to_step
from etl.silver import (
    MAX_IMPUTED_GAP,
    NO_READING,
    REJECTED_READING,
    SETTLE_DELAY,
    BronzeRow,
    _processing_range,
    build_silver_rows,
    clean_reading,
    impute_consumption,
)

T0 = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
CAPACITE = 200.0


def _payload(**champs: Any) -> dict[str, Any]:
    mesure: dict[str, Any] = {
        "timestamp": T0.isoformat(),
        "site_id": "SITE001",
        "site_type": "office",
        "consumption_kw": 150.0,
        "voltage_v": 401.0,
        "current_a": 230.0,
        "power_factor": 0.91,
        "temperature_celsius": 12.0,
        "humidity_percent": 45.0,
        "null_reasons": [],
        "data_quality": "good",
    }
    return {**mesure, **champs}


def _clean(**champs: Any) -> dict[str, Any]:
    row, rejection = clean_reading(
        "SITE001", T0, BronzeRow(1, _payload(**champs)), CAPACITE
    )
    assert rejection is None
    return row


def test_mesure_valide_recopiee() -> None:
    row = _clean()
    assert row["bronze_id"] == 1
    assert row["consumption_kw_raw"] == 150.0
    assert row["data_quality"] == "good"
    assert row["null_reasons"] == []


def test_valeur_hors_plage_mise_a_null_avec_raison() -> None:
    row = _clean(voltage_v=520.0, power_factor=1.4)
    assert row["voltage_v"] is None
    assert row["power_factor"] is None
    assert row["null_reasons"] == [
        "voltage_v_out_of_range",
        "power_factor_out_of_range",
    ]
    assert row["data_quality"] == "partial"  # était good


def test_depassement_de_capacite_conserve() -> None:
    # 230 kW pour 200 kW de capacité : un pic, pas une erreur
    row = _clean(consumption_kw=230.0)
    assert row["consumption_kw_raw"] == 230.0
    assert row["null_reasons"] == []


def test_consommation_aberrante_ou_negative_mise_a_null() -> None:
    assert _clean(consumption_kw=401.0)["consumption_kw_raw"] is None  # > 2 × capacité
    assert _clean(consumption_kw=-1.0)["null_reasons"] == [
        "consumption_kw_out_of_range"
    ]


def test_raisons_de_l_api_conservees() -> None:
    row = _clean(
        consumption_kw=None,
        null_reasons=["consumption_sensor_failure"],
        data_quality="partial",
    )
    assert row["consumption_kw_raw"] is None
    assert row["null_reasons"] == ["consumption_sensor_failure"]
    assert row["data_quality"] == "partial"


def test_mesure_hors_contrat_mise_en_quarantaine() -> None:
    bronze = BronzeRow(7, _payload(data_quality="excellent"))
    row, rejection = clean_reading("SITE001", T0, bronze, CAPACITE)

    assert rejection is not None
    assert rejection.bronze_id == 7
    assert rejection.errors[0]["loc"] == ["data_quality"]
    assert row["bronze_id"] == 7
    assert row["null_reasons"] == [REJECTED_READING]
    assert row["data_quality"] == "critical"


def test_imputation_d_un_trou_court() -> None:
    assert impute_consumption([10.0, None, None, 40.0]) == [
        (10.0, "none"),
        (20.0, "linear_interpolation"),
        (30.0, "linear_interpolation"),
        (40.0, "none"),
    ]


def test_trou_trop_long_non_impute() -> None:
    raw = [10.0, *([None] * (MAX_IMPUTED_GAP + 1)), 40.0]
    assert all(v is None for v, _ in impute_consumption(raw)[1:-1])


def test_trou_le_plus_long_impute() -> None:
    raw = [10.0, *([None] * MAX_IMPUTED_GAP), 40.0]
    assert all(m == "linear_interpolation" for _, m in impute_consumption(raw)[1:-1])


def test_trou_en_bordure_non_impute() -> None:
    # Sans valeur de part et d'autre, on ne devine pas
    assert impute_consumption([None, 10.0, None]) == [
        (None, "none"),
        (10.0, "none"),
        (None, "none"),
    ]


def _bronze(minutes: list[int], **champs: Any) -> dict[datetime, BronzeRow]:
    return {T0 + m * STEP: BronzeRow(100 + m, _payload(**champs)) for m in minutes}


def test_minutes_sans_mesure_presentes_dans_silver() -> None:
    bronze = _bronze([0, 1, 4])
    rows, rejections = build_silver_rows(
        "SITE001", CAPACITE, T0, T0 + 4 * STEP, bronze, output_from=T0
    )

    assert [r["horodatage"] for r in rows] == [T0 + m * STEP for m in range(5)]
    manquantes = [r for r in rows if r["bronze_id"] is None]
    assert len(manquantes) == 2
    assert manquantes[0]["null_reasons"] == [NO_READING]
    assert manquantes[0]["consumption_kw_raw"] is None
    assert manquantes[0]["consumption_kw_imputed"] == 150.0
    assert manquantes[0]["imputation_method"] == "linear_interpolation"
    assert rejections == []


def test_charge_calculee_sur_la_valeur_finale() -> None:
    rows, _ = build_silver_rows(
        "SITE001", CAPACITE, T0, T0, _bronze([0], consumption_kw=230.0), output_from=T0
    )
    assert rows[0]["load_percent"] == 115.0


def test_contexte_sert_a_l_imputation_sans_etre_ecrit() -> None:
    # Minute 0 : contexte ; minutes 1-2 : trou ; minute 3 : nouvelle mesure
    bronze = _bronze([0, 3])
    output_from = T0 + STEP
    rows, _ = build_silver_rows(
        "SITE001", CAPACITE, T0, T0 + 3 * STEP, bronze, output_from=output_from
    )

    assert rows[0]["horodatage"] == output_from
    assert rows[0]["imputation_method"] == "linear_interpolation"
    assert len(rows) == 3


def test_quarantaine_limitee_a_la_periode_ecrite() -> None:
    bronze = _bronze([0, 1], data_quality="excellent")
    _, rejections = build_silver_rows(
        "SITE001", CAPACITE, T0, T0 + STEP, bronze, output_from=T0 + STEP
    )
    assert [r.bronze_id for r in rejections] == [101]


def test_periode_vide() -> None:
    rows, _ = build_silver_rows(
        "SITE001", CAPACITE, T0, T0 - timedelta(minutes=1), {}, output_from=T0
    )
    assert rows == []


# --- Période à traiter (base remplacée) ---------------------------------------


class _FakeConn:
    """Connexion dont execute(...).one() renvoie les bornes silver/bronze."""

    def __init__(self, **bornes: datetime | None) -> None:
        self._row = SimpleNamespace(**bornes)

    def execute(self, *_: Any) -> SimpleNamespace:
        return SimpleNamespace(one=lambda: self._row)


def _periode(now: datetime, **bornes: datetime | None) -> Any:
    return _processing_range(_FakeConn(**bornes), "SITE001", now)  # type: ignore[arg-type]


def test_periode_prolongee_jusqu_a_now_moins_le_delai_si_bronze_en_retard() -> None:
    now = T0 + timedelta(minutes=30, seconds=45)
    periode = _periode(
        now, silver_last=None, bronze_first=T0, bronze_last=T0 + 10 * STEP
    )
    assert periode == (T0, floor_to_step(now - SETTLE_DELAY))
    assert periode[1] == T0 + 28 * STEP


def test_periode_finit_a_bronze_last_quand_bronze_est_a_jour() -> None:
    now = T0 + timedelta(minutes=11)
    bronze_last = T0 + 10 * STEP
    periode = _periode(
        now, silver_last=T0 + 5 * STEP, bronze_first=T0, bronze_last=bronze_last
    )
    assert periode == (T0, bronze_last)  # marge de retraitement bornée à bronze_first


def test_aucune_periode_sans_bronze() -> None:
    assert _periode(T0, silver_last=None, bronze_first=None, bronze_last=None) is None
