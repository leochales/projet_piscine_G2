from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from common.db import get_session


class FausseSession:
    """Remplace la vraie session : renvoie des lignes écrites à la main."""

    def __init__(self, lignes: list[dict[str, Any]]) -> None:
        self.lignes = lignes

    def execute(
        self, requete: Any, parametres: dict[str, Any] | None = None
    ) -> "FausseSession":
        return self

    def mappings(self) -> "FausseSession":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.lignes


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_derniere_mesure_renvoie_une_ligne_par_site(client: TestClient) -> None:
    lignes: list[dict[str, Any]] = [
        {
            "id_site": "SITE001",
            "nom": "Bureau Paris La Défense",
            "horodatage": datetime(2026, 10, 21, 14, 30, tzinfo=UTC),
            "consommation_kw": 87.34,
            "data_quality": "good",
        },
        {
            "id_site": "SITE002",
            "nom": "Usine Lyon Vénissieux",
            "horodatage": datetime(2026, 10, 21, 14, 30, tzinfo=UTC),
            "consommation_kw": None,
            "data_quality": "degraded",
        },
    ]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/derniere-mesure")

    assert response.status_code == 200
    corps = response.json()
    assert len(corps) == 2
    assert corps[0]["nom"] == "Bureau Paris La Défense"
    assert corps[0]["horodatage"] == "2026-10-21T14:30:00Z"
    assert corps[1]["consommation_kw"] is None


def test_derniere_mesure_renvoie_une_liste_vide_sans_donnees(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get("/api/sites/derniere-mesure")

    assert response.status_code == 200
    assert response.json() == []


def test_consommation_calcule_le_cout_en_euros(client: TestClient) -> None:
    lignes: list[dict[str, Any]] = [
        {
            "heure": datetime(2026, 10, 21, 13, 0, tzinfo=UTC),
            "consommation_kwh": Decimal("500.000"),
        },
        {
            "heure": datetime(2026, 10, 21, 14, 0, tzinfo=UTC),
            "consommation_kwh": None,
        },
    ]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/SITE001/consommation")

    assert response.status_code == 200
    corps = response.json()
    assert corps[0]["consommation_kwh"] == 500.0
    assert corps[0]["cout_eur"] == 70.0
    assert corps[1]["consommation_kwh"] is None
    assert corps[1]["cout_eur"] is None


def test_consommation_refuse_une_date_invalide(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get("/api/sites/SITE001/consommation?debut=pas-une-date")

    assert response.status_code == 422


def test_consommation_refuse_un_id_site_invalide(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get(f"/api/sites/{'A' * 21}/consommation")

    assert response.status_code == 422
