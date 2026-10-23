from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from etl.schemas import EnergyReading, ReadingKey, SiteInfo

# Mesure réelle renvoyée par GET /api/v1/readings (22/10/2026)
MESURE = {
    "timestamp": "2026-10-21T00:00:00Z",
    "site_id": "SITE001",
    "site_type": "office",
    "consumption_kw": 62.79,
    "consumption_kwh": 62.79,
    "voltage_v": 403.2,
    "current_a": 94.64,
    "power_factor": 0.907,
    "temperature_celsius": -3.2,
    "humidity_percent": 42.4,
    "null_reasons": [],
    "data_quality": "good",
}


def test_cle_de_mesure_valide() -> None:
    # Mesure réelle renvoyée par GET /api/v1/readings (22/10/2026)
    cle = ReadingKey.model_validate(
        {
            "timestamp": "2026-10-21T00:00:00Z",
            "site_id": "SITE001",
            "site_type": "office",
            "consumption_kw": 62.79,
            "null_reasons": [],
            "data_quality": "good",
        }
    )
    assert cle.site_id == "SITE001"
    assert cle.timestamp == datetime(2026, 10, 21, tzinfo=UTC)


def test_date_sans_fuseau_lue_en_utc() -> None:
    # /current et /alerts renvoient des dates sans fuseau
    cle = ReadingKey.model_validate(
        {"site_id": "SITE001", "timestamp": "2026-10-22T13:14:39.803236"}
    )
    assert cle.timestamp.tzinfo is UTC
    assert cle.timestamp.hour == 13


def test_date_avec_decalage_convertie_en_utc() -> None:
    cle = ReadingKey.model_validate(
        {"site_id": "SITE001", "timestamp": "2026-10-21T02:00:00+02:00"}
    )
    assert cle.timestamp == datetime(2026, 10, 21, tzinfo=UTC)


@pytest.mark.parametrize(
    "mesure",
    [
        {"site_id": "SITE001"},
        {"site_id": "SITE001", "timestamp": "hier"},
        {"site_id": "", "timestamp": "2026-10-21T00:00:00Z"},
    ],
)
def test_cle_invalide_refusee(mesure: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ReadingKey.model_validate(mesure)


def test_site_capacite_nulle_refusee() -> None:
    site = {
        "site_id": "SITE001",
        "site_type": "office",
        "site_name": "Bureau Paris La Défense",
        "location": "Paris, France",
        "capacity_kw": 200.0,
        "status": "active",
    }
    assert SiteInfo.model_validate(site).capacity_kw == 200.0
    with pytest.raises(ValidationError):
        SiteInfo.model_validate({**site, "capacity_kw": 0})


def test_mesure_complete_valide() -> None:
    mesure = EnergyReading.model_validate(MESURE)
    assert mesure.timestamp == datetime(2026, 10, 21, tzinfo=UTC)
    assert mesure.consumption_kw == 62.79
    # consumption_kwh vaut toujours consumption_kw : volontairement ignoré
    assert not hasattr(mesure, "consumption_kwh")


def test_perte_reseau_tous_les_champs_nuls() -> None:
    mesure = EnergyReading.model_validate(
        {
            "timestamp": "2026-10-21T14:25:00Z",
            "site_id": "SITE003",
            "site_type": "datacenter",
            "consumption_kw": None,
            "voltage_v": None,
            "current_a": None,
            "power_factor": None,
            "temperature_celsius": None,
            "humidity_percent": None,
            "null_reasons": ["network_loss"],
            "data_quality": "critical",
        }
    )
    assert mesure.consumption_kw is None
    assert mesure.null_reasons == ["network_loss"]
    assert mesure.data_quality == "critical"


def test_valeurs_par_defaut_quand_les_champs_optionnels_manquent() -> None:
    mesure = EnergyReading.model_validate(
        {
            "timestamp": "2026-10-21T00:00:00Z",
            "site_id": "SITE001",
            "site_type": "office",
        }
    )
    assert mesure.null_reasons == []
    assert mesure.data_quality == "good"
    assert mesure.voltage_v is None


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("null_reasons", ["capteur_inconnu"]),
        ("data_quality", "excellent"),
        ("consumption_kw", "beaucoup"),
        ("timestamp", "hier"),
        ("site_type", None),
    ],
)
def test_mesure_hors_contrat_refusee(champ: str, valeur: object) -> None:
    with pytest.raises(ValidationError):
        EnergyReading.model_validate({**MESURE, champ: valeur})


def test_valeur_physiquement_aberrante_acceptee_par_le_contrat() -> None:
    # Les plages physiques sont contrôlées en silver (NULL + raison), pas ici :
    # une tension à 999 V ne doit pas envoyer toute la mesure en quarantaine
    mesure = EnergyReading.model_validate({**MESURE, "voltage_v": 999.0})
    assert mesure.voltage_v == 999.0
