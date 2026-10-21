from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from common.db import get_session


class FausseSession:
    """Remplace la vraie session : renvoie des lignes écrites à la main."""

    def __init__(self, lignes: list[dict[str, Any]]) -> None:
        self.lignes = lignes

    def execute(self, requete: Any) -> "FausseSession":
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
    lignes = [
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
