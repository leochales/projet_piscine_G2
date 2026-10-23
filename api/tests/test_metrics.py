from fastapi.testclient import TestClient

from api.main import app
from api.routers.health import database_status


def test_metrics_expose_les_requetes_au_format_prometheus() -> None:
    client = TestClient(app)
    app.dependency_overrides[database_status] = lambda: True
    try:
        client.get("/api/health")
        response = client.get("/metrics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert 'handler="/api/health"' in response.text
    assert "http_request_duration_seconds" in response.text


def test_metrics_n_apparait_pas_dans_le_contrat_openapi() -> None:
    schema = TestClient(app).get("/api/openapi.json").json()
    assert "/metrics" not in schema["paths"]
