from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers.health import database_status


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_ok_quand_la_base_repond(client: TestClient) -> None:
    app.dependency_overrides[database_status] = lambda: True

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_503_quand_la_base_est_injoignable(client: TestClient) -> None:
    app.dependency_overrides[database_status] = lambda: False

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}


def test_swagger_est_servi_sous_api(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"] == "EnerVision API"
    assert client.get("/api/redoc").status_code == 404
