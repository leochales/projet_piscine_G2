"""Configuration pytest du service."""

import mlflow
import pytest
from mlflow import MlflowClient


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Aucun test pour l'instant : pytest renvoie 5 et ferait échouer le hook pre-push
    # (déclenché aussi par les changements dans common/). À retirer avec les premiers tests.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK


@pytest.fixture
def client(tmp_path, monkeypatch):
    """MLflow local dans un dossier temporaire, à la place du serveur, comme le test
    de model.dataset. Utilisé par les tests du registre et de la prévision."""
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    # Stockage en fichiers : suffisant pour un test, sans les dépendances du serveur
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    uri = (tmp_path / "mlruns").as_uri()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    yield MlflowClient()
    # Adresses globales de MLflow remises à zéro : le dossier temporaire va disparaître
    mlflow.set_tracking_uri(None)
    mlflow.set_registry_uri(None)
