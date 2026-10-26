import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from etl import silver
from etl.bootstrap import BOOTSTRAP_DEPTH
from etl.grid import STEP, floor_to_step
from etl.silver import (
    MAX_IMPUTED_GAP,
    MAX_MINUTES_PER_RUN,
    NO_READING,
    REJECTED_READING,
    REPROCESS_MARGIN,
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


def test_contexte_apres_la_periode_sert_a_l_imputation() -> None:
    # Trou en fin de période, suivi d'une mesure déjà en silver (rattrapage)
    bronze = _bronze([0, 3])
    rows, _ = build_silver_rows(
        "SITE001",
        CAPACITE,
        T0,
        T0 + 3 * STEP,
        bronze,
        output_from=T0,
        output_to=T0 + 2 * STEP,
    )
    assert [r["horodatage"] for r in rows] == [T0, T0 + STEP, T0 + 2 * STEP]
    assert rows[-1]["imputation_method"] == "linear_interpolation"


def test_periode_vide() -> None:
    rows, _ = build_silver_rows(
        "SITE001", CAPACITE, T0, T0 - timedelta(minutes=1), {}, output_from=T0
    )
    assert rows == []


# --- Période à traiter (base remplacée) ---------------------------------------


class _FakeConn:
    """Connexion dont execute(...).one() renvoie les bornes silver/bronze."""

    def __init__(self, **bornes: Any) -> None:
        # Par défaut, la première mesure de bronze est déjà traitée en silver
        # si silver la couvre
        bornes.setdefault(
            "bronze_first_in_silver",
            bornes["bronze_first"] is not None
            and bornes["silver_first"] is not None
            and bornes["silver_first"]
            <= bornes["bronze_first"]
            <= bornes["silver_last"],
        )
        self._row = SimpleNamespace(**bornes)

    def execute(self, *_: Any) -> SimpleNamespace:
        return SimpleNamespace(one=lambda: self._row)


def _periode(now: datetime, **bornes: Any) -> Any:
    return _processing_range(_FakeConn(**bornes), "SITE001", now)  # type: ignore[arg-type]


def test_periode_prolongee_jusqu_a_now_moins_le_delai_si_bronze_en_retard() -> None:
    now = T0 + timedelta(minutes=30, seconds=45)
    periode = _periode(
        now,
        silver_first=None,
        silver_last=None,
        bronze_first=T0,
        bronze_last=T0 + 10 * STEP,
    )
    assert periode == (T0, floor_to_step(now - SETTLE_DELAY))
    assert periode[1] == T0 + 29 * STEP


def test_periode_finit_a_bronze_last_quand_bronze_est_a_jour() -> None:
    # La minute en cours vient d'être collectée : bronze_last > now − délai
    now = T0 + timedelta(minutes=11, seconds=5)
    bronze_last = T0 + 11 * STEP
    assert floor_to_step(now - SETTLE_DELAY) < bronze_last
    periode = _periode(
        now,
        silver_first=T0,
        silver_last=T0 + 5 * STEP,
        bronze_first=T0,
        bronze_last=bronze_last,
    )
    assert periode == (T0, bronze_last)  # marge de retraitement bornée à bronze_first


def test_periode_repart_de_la_marge_apres_silver_last() -> None:
    now = T0 + timedelta(hours=1, seconds=5)
    periode = _periode(
        now,
        silver_first=T0,
        silver_last=T0 + 59 * STEP,
        bronze_first=T0,
        bronze_last=T0 + 60 * STEP,
    )
    assert periode == (T0 + 59 * STEP - REPROCESS_MARGIN, T0 + 60 * STEP)


def test_historique_insere_apres_coup_est_retraite_depuis_le_debut() -> None:
    # Amorçage relancé : bronze a 7 jours avant la première minute de silver
    now = T0 + timedelta(hours=1, seconds=5)
    debut_amorcage = T0 - timedelta(days=7)
    periode = _periode(
        now,
        silver_first=T0,
        silver_last=T0 + 59 * STEP,
        bronze_first=debut_amorcage,
        bronze_last=T0 + 60 * STEP,
    )
    assert periode == (debut_amorcage, T0 + 60 * STEP)


def test_site_jamais_collecte_commence_a_now_moins_le_delai() -> None:
    # Ni bronze ni silver : silver matérialise la minute du passage
    now = T0 + timedelta(seconds=45)
    periode = _periode(
        now,
        silver_first=None,
        silver_last=None,
        bronze_first=None,
        bronze_last=None,
    )
    assert periode == (T0 - STEP, T0 - STEP)


def test_site_jamais_collecte_avance_depuis_silver_last() -> None:
    now = T0 + timedelta(minutes=30, seconds=5)
    periode = _periode(
        now,
        silver_first=T0,
        silver_last=T0 + 28 * STEP,
        bronze_first=None,
        bronze_last=None,
    )
    assert periode == (T0 + 28 * STEP - REPROCESS_MARGIN, T0 + 29 * STEP)


def test_amorcage_apres_des_minutes_no_reading_les_reprend() -> None:
    # Site sans mesure depuis 10 jours (no_reading en silver), puis amorcé :
    # la première mesure de bronze n'est en silver qu'en no_reading
    now = T0 + timedelta(hours=1, seconds=5)
    debut_amorcage = T0 - timedelta(days=7)
    periode = _periode(
        now,
        silver_first=T0 - timedelta(days=10),
        silver_last=T0 + 59 * STEP,
        bronze_first=debut_amorcage,
        bronze_last=T0 + 58 * STEP,
        bronze_first_in_silver=False,
    )
    assert periode == (debut_amorcage, T0 + 59 * STEP)


def test_rattrapage_borne_a_max_minutes_par_passage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Site réactivé : une mesure isolée il y a 180 jours, silver vide
    vieille = T0 - timedelta(days=180)
    with caplog.at_level(logging.INFO, logger=silver.__name__):
        periode = _periode(
            T0 + timedelta(seconds=5),
            silver_first=None,
            silver_last=None,
            bronze_first=vieille,
            bronze_last=vieille,
        )
    assert periode == (vieille, vieille + (MAX_MINUTES_PER_RUN - 1) * STEP)
    assert "rattrapage" in caplog.text


def test_amorcage_de_7_jours_traite_en_un_passage() -> None:
    now = T0 + timedelta(minutes=3, seconds=5)
    periode = _periode(
        now,
        silver_first=None,
        silver_last=None,
        bronze_first=T0 - BOOTSTRAP_DEPTH,
        bronze_last=T0 + 3 * STEP,
    )
    assert periode == (T0 - BOOTSTRAP_DEPTH, T0 + 3 * STEP)


def _simuler_passages(
    silver_first: datetime | None,
    silver_last: datetime | None,
    bronze_first: datetime | None,
    bronze_last: datetime | None,
    now: datetime,
) -> list[tuple[datetime, datetime]]:
    """Enchaîne les passages (à ``now`` fixe) jusqu'à ce que silver soit à jour.

    Vérifie à chaque passage que silver reste d'un seul tenant et que le
    travail est borné.
    """
    traitees: list[tuple[datetime, datetime]] = []
    cible = floor_to_step(now - SETTLE_DELAY)
    for _ in range(100):
        periode = _periode(
            now,
            silver_first=silver_first,
            silver_last=silver_last,
            bronze_first=bronze_first,
            bronze_last=bronze_last,
            bronze_first_in_silver=bronze_first is not None
            and any(d <= bronze_first <= f for d, f in traitees),
        )
        assert periode is not None
        debut, fin = periode
        assert (fin - debut) // STEP + 1 <= MAX_MINUTES_PER_RUN
        if silver_first is not None and silver_last is not None:
            # Recouvre ou prolonge silver : jamais de trou
            assert debut <= silver_last + STEP and fin >= silver_first - STEP
        traitees.append(periode)
        silver_first = debut if silver_first is None else min(silver_first, debut)
        silver_last = fin if silver_last is None else max(silver_last, fin)
        a_jour = silver_last >= max(cible, bronze_last or cible)
        if a_jour and (bronze_first is None or silver_first <= bronze_first):
            return traitees
    raise AssertionError("le rattrapage ne termine pas")


def test_reactivation_rattrapee_progressivement_jusqu_a_now() -> None:
    now = T0 + timedelta(seconds=5)
    vieille = T0 - timedelta(days=30)
    passages = _simuler_passages(None, None, vieille, vieille, now)

    assert passages[0][0] == vieille
    assert passages[-1][1] == floor_to_step(now - SETTLE_DELAY)
    assert len(passages) == 4  # 30 jours à 8 jours par passage


def test_historique_ancien_rattrape_en_reculant_sans_trou(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Ligne bronze isolée 30 jours avant le début de silver
    now = T0 + timedelta(hours=1, seconds=5)
    vieille = T0 - timedelta(days=30)
    with caplog.at_level(logging.INFO, logger=silver.__name__):
        passages = _simuler_passages(T0, T0 + 59 * STEP, vieille, T0 + 60 * STEP, now)

    # Premier passage : recul d'un passage, en recouvrant la marge de silver
    assert passages[0][1] == T0 + REPROCESS_MARGIN
    assert passages[0][0] == passages[0][1] - (MAX_MINUTES_PER_RUN - 1) * STEP
    assert min(d for d, _ in passages) == vieille
    assert max(f for _, f in passages) == T0 + 60 * STEP
    assert len(passages) == 5  # 3 reculs, la mesure isolée, puis le front
    assert "recule" in caplog.text


# --- Orchestration : isolation des erreurs et code de sortie ------------------


class _FakeEngine:
    @contextmanager
    def connect(self) -> Iterator[None]:
        yield None

    begin = connect


@pytest.fixture
def fake_transform(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"errors": {}}

    def transform_site(_: Any, id_site: str, *__: Any) -> int:
        if id_site in state["errors"]:
            raise state["errors"][id_site]
        return 10

    monkeypatch.setattr(silver, "get_engine", _FakeEngine)
    monkeypatch.setattr(
        silver,
        "load_declared_sites",
        lambda _: {"SITE001": 100.0, "SITE002": 100.0, "SITE003": 100.0},
    )
    monkeypatch.setattr(silver, "transform_site", transform_site)
    return state


def test_une_erreur_inattendue_sur_un_site_n_arrete_pas_les_autres(
    fake_transform: dict[str, Any],
) -> None:
    fake_transform["errors"] = {"SITE001": TypeError("payload exotique")}
    assert silver.transform(T0) == {
        "sites": 3,
        "rows_written": 20,
        "sites_in_error": 1,
    }


def test_tous_les_sites_en_echec_sort_en_1(fake_transform: dict[str, Any]) -> None:
    fake_transform["errors"] = {
        "SITE001": OperationalError("UPDATE", {}, Exception("droit refusé")),
        "SITE002": TypeError("payload exotique"),
        "SITE003": OperationalError("UPDATE", {}, Exception("droit refusé")),
    }
    with pytest.raises(SystemExit) as exc:
        silver.transform(T0)
    assert exc.value.code == silver.EXIT_ALL_SITES_FAILED
