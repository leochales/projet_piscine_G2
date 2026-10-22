"""ETL — Couche Bronze.

Collecte les données brutes depuis l'API Mock et les insère dans :
  - bronze.raw_readings  (JSONB — payload complet du reading + métadonnées
                          site sous la clé ``_site``)

Les sites inconnus de ``app.site`` sont ignorés : le référentiel des sites
est géré par l'application, pas par l'API Mock.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import text

from common.db import get_engine
from etl.api_client import get_current_reading, get_sites

logger = logging.getLogger(__name__)


def _get_known_sites() -> dict[str, dict]:
    """Charge les sites déclarés dans app.site (filtre pour l'ingestion)."""
    sql = text("""
        SELECT id_site, capacite_kw, statut
        FROM app.site
    """)
    with get_engine().connect() as conn:
        return {
            r.id_site: {"capacite_kw": float(r.capacite_kw), "statut": r.statut}
            for r in conn.execute(sql)
        }


def _insert_reading(site: dict, reading: dict, known: dict[str, dict]) -> bool:
    """Insère une mesure brute dans bronze.raw_readings (ignore les doublons)."""
    id_site = site.get("id") or site.get("site_id")
    if id_site not in known:
        return False

    raw_ts = reading.get("timestamp")
    try:
        ts = datetime.fromisoformat(str(raw_ts))
    except (ValueError, TypeError):
        ts = datetime.now(tz=UTC)

    payload = {
        **reading,
        "_site": {
            "id_site": id_site,
            "site_name": site.get("name") or site.get("site_name", ""),
            "site_type": site.get("type") or site.get("site_type", "office"),
            "capacite_kw": known[id_site]["capacite_kw"],
            "location": site.get("location"),
            "status": site.get("status", "active"),
        },
    }

    sql = text("""
        INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
        VALUES (:id_site, :horodatage, :payload)
        ON CONFLICT (id_site, horodatage) DO NOTHING
    """)

    with get_engine().begin() as conn:
        result = conn.execute(
            sql,
            {
                "id_site": id_site,
                "horodatage": ts,
                "payload": json.dumps(payload),
            },
        )
        return result.rowcount > 0


def run() -> dict[str, int]:
    """Point d'entrée : collecte et insère la dernière mesure de chaque site."""
    logger.info("[COLLECT] Démarrage")

    known = _get_known_sites()
    if not known:
        logger.warning("[COLLECT] Aucun site dans app.site — rien à collecter")
        return {"sites": 0, "readings_inserted": 0, "readings_skipped": 0}

    sites = get_sites()
    if not sites:
        logger.warning("[COLLECT] Aucun site récupéré — API Mock inaccessible ?")
        return {"sites": 0, "readings_inserted": 0, "readings_skipped": 0}

    logger.info(
        "[COLLECT] %d site(s) API, %d site(s) connus en base", len(sites), len(known)
    )

    inserted = skipped = 0
    for site in sites:
        id_site = site.get("id") or site.get("site_id")
        if id_site not in known:
            continue
        reading = get_current_reading(id_site)
        if reading is None:
            logger.warning("[COLLECT] Pas de mesure pour site %s", id_site)
            continue
        if _insert_reading(site, reading, known):
            inserted += 1
        else:
            skipped += 1

    logger.info(
        "[COLLECT] Mesures : %d insérées, %d doublons ignorés", inserted, skipped
    )
    return {
        "sites": len(known),
        "readings_inserted": inserted,
        "readings_skipped": skipped,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run()
