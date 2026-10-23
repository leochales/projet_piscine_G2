import json
import logging
import sys
from collections.abc import Iterator

import pytest

from common.logs import JsonFormatter, configure_logging


def lire_ligne(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lignes = capsys.readouterr().out.strip().splitlines()
    return json.loads(lignes[-1])


@pytest.fixture(autouse=True)
def restaurer_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def test_un_log_devient_une_ligne_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api", level="INFO")

    logging.getLogger("api.test").info(
        "site %s collecté", "SITE001", extra={"duree_ms": 12}
    )

    ligne = lire_ligne(capsys)
    assert ligne["service"] == "api"
    assert ligne["level"] == "info"
    assert ligne["logger"] == "api.test"
    assert ligne["message"] == "site SITE001 collecté"
    assert ligne["duree_ms"] == 12  # champ passé par extra
    assert "timestamp" in ligne


def test_le_niveau_filtre_les_logs(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api", level="WARNING")

    logging.getLogger("api.test").info("ignoré")
    logging.getLogger("api.test").warning("gardé")

    assert [json.loads(x)["message"] for x in capsys.readouterr().out.splitlines()] == [
        "gardé"
    ]


def test_les_logs_d_uvicorn_passent_aussi_en_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.access").addHandler(logging.NullHandler())
    configure_logging("api", level="INFO")

    logging.getLogger("uvicorn.access").info("GET /api/health 200")

    assert lire_ligne(capsys)["logger"] == "uvicorn.access"
    assert logging.getLogger("uvicorn.access").handlers == []


def test_une_exception_est_incluse_dans_le_json() -> None:
    formatter = JsonFormatter("etl")
    try:
        raise ValueError("mesure invalide")
    except ValueError:
        record = logging.getLogger("etl").makeRecord(
            "etl",
            logging.ERROR,
            __file__,
            1,
            "échec",
            (),
            exc_info=sys.exc_info(),
        )

    ligne = json.loads(formatter.format(record))

    assert ligne["level"] == "error"
    assert "ValueError: mesure invalide" in str(ligne["exception"])


def test_les_lectures_de_metrics_ne_sont_pas_loguees(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("api", level="INFO")
    access = logging.getLogger("uvicorn.access")

    access.info('%s - "%s %s HTTP/%s" %d', "10.0.0.1", "GET", "/metrics", "1.1", 200)
    access.info('%s - "%s %s HTTP/%s" %d', "10.0.0.1", "GET", "/api/health", "1.1", 200)

    messages = [json.loads(x)["message"] for x in capsys.readouterr().out.splitlines()]
    assert len(messages) == 1
    assert "/api/health" in messages[0]


def test_configurer_deux_fois_n_ajoute_pas_le_filtre_deux_fois() -> None:
    configure_logging("api")
    configure_logging("api")
    filtres = logging.getLogger("uvicorn.access").filters
    assert sum(type(f).__name__ == "IgnorerScrapeMetrics" for f in filtres) == 1
