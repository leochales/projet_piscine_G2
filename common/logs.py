"""Logs au format JSON, une ligne par événement, sur la sortie standard.

Format commun à tous les services (API, ETL, modèle) : Loki les collecte via Docker
et Grafana peut filtrer par service, niveau ou logger sans analyser de texte libre.

    from common.logs import configure_logging
    configure_logging("api")
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

# Attributs standards d'un LogRecord : tout le reste vient de extra={...} et est ajouté au JSON
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
}

# Loggers d'uvicorn : sans eux, les logs d'accès et de démarrage resteraient en texte
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class IgnorerScrapeMetrics(logging.Filter):
    """Retire des logs d'accès les lectures de /metrics par Prometheus (une toutes les 15 s)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Logs d'accès d'uvicorn : args = (client, méthode, chemin, version HTTP, statut)
        args = record.args
        return not (
            isinstance(args, tuple) and len(args) >= 3 and args[2] == "/metrics"
        )


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(
            {
                key: value
                for key, value in vars(record).items()
                if key not in _STANDARD_ATTRS
            }
        )
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(service: str, level: str | None = None) -> None:
    """Envoie tous les logs (application et uvicorn) en JSON sur la sortie standard."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, IgnorerScrapeMetrics) for f in access.filters):
        access.addFilter(IgnorerScrapeMetrics())
