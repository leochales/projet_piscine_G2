from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from etl.schemas import ReadingKey, SiteInfo


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
