import importlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import api.main
from common.config import get_settings


@pytest.fixture
def app_sans_docs(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # L'application lit API_DOCS_ENABLED à l'import : on la recrée, puis on restaure
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    get_settings.cache_clear()
    try:
        yield TestClient(importlib.reload(api.main).app)
    finally:
        monkeypatch.delenv("API_DOCS_ENABLED")
        get_settings.cache_clear()
        importlib.reload(api.main)


def test_swagger_et_openapi_sont_publies_par_defaut() -> None:
    client = TestClient(api.main.app)
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200


def test_swagger_et_openapi_masques_quand_les_docs_sont_desactivees(
    app_sans_docs: TestClient,
) -> None:
    assert app_sans_docs.get("/api/docs").status_code == 404
    assert app_sans_docs.get("/api/openapi.json").status_code == 404
