"""Configuration pytest du service."""

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Aucun test pour l'instant : pytest renvoie 5 et ferait échouer le hook pre-push
    # (déclenché aussi par les changements dans common/). À retirer avec les premiers tests.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
