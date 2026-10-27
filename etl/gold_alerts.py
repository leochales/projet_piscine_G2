"""ETL — Alertes dans gold (silver → gold.alerte, SMARTOPS-26).

La détection est faite par la fonction SQL ``gold.detecter_alertes()``
(db/17_gold_alertes.sql), testée en CI par db/tests/test_gold_alertes.sql.
Même règle pour tous les suivis : une alerte commence après 3 minutes en
défaut consécutives, et se termine après 3 minutes sans défaut :
  - threshold : consommation mesurée au-dessus du seuil du site
    (app.site.seuil_alerte_pct) ; critical au-delà de 110 % de la capacité ;
  - sensor : capteur de consommation (high) ou électrique (medium) en panne,
    lu dans les raisons des valeurs manquantes de silver.

Chaque alerte est une seule ligne, mise à jour à chaque passage.

Les alertes de l'API Mock ne sont pas reprises : elles sont tirées au hasard
à chaque appel, sans identifiant stable (voir etl/api_client.py).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Connection, text

from common.db import get_engine
from common.logs import configure_logging

logger = logging.getLogger(__name__)


def upsert_alerts(conn: Connection) -> list[Any]:
    """Crée ou met à jour les alertes. Retourne les alertes écrites."""
    sql = text(
        "SELECT id_site, type, capteur, debut, en_cours FROM gold.detecter_alertes()"
    )
    return list(conn.execute(sql))


def detect() -> dict[str, int]:
    """Met à jour gold.alerte pour tous les sites actifs."""
    with get_engine().begin() as conn:
        alerts = upsert_alerts(conn)
    for a in alerts:
        logger.info(
            "site=%s : alerte %s du %s %s",
            a.id_site,
            f"{a.type}/{a.capteur}" if a.capteur else a.type,
            a.debut.isoformat(),
            "en cours" if a.en_cours else "terminée",
        )
    summary = {
        "alerts_written": len(alerts),
        "in_progress": sum(1 for a in alerts if a.en_cours),
    }
    # Une ligne à chaque passage, même sans alerte : prouve que l'ETL a tourné
    logger.info(
        "alertes : %d écrite(s), dont %d en cours",
        summary["alerts_written"],
        summary["in_progress"],
    )
    return summary


if __name__ == "__main__":
    configure_logging("etl")
    detect()
