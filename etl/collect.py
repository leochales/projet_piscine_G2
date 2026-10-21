"""ETL — Couche Bronze.

Collecte les données brutes depuis l'API Mock et les insère dans :
  - bronze.raw_readings  (1 seule table JSONB — merge site + reading)

Architecture Bronze :
  Le payload JSONB contient le merge complet du dict site (capacity_kw,
  site_name, site_type, location, status) et du dict reading (consumption_kw,
  voltage_v, null_reasons, …). Pas de table dim_sites séparée — tout est
  auto-porté par chaque ligne, ce qui permet de rejouer Silver sans perte
  et sans jointure externe.

Règle d'or : on n'écrase jamais une ligne de bronze une fois insérée.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from common.db import get_engine
from etl.api_client import get_current_reading, get_readings_history, get_sites

logger = logging.getLogger(__name__)


def _quality_from_reading(reading: dict) -> str:
    """Déduit le niveau de qualité d'une mesure depuis null_reasons."""
    consumption_kw = reading.get("consumption_kw")
    null_reasons: list[str] = reading.get("null_reasons") or []

    if consumption_kw is None:
        return "critical" if null_reasons else "degraded"
    if null_reasons:
        return "partial"
    return "good"


def _insert_reading(site: dict, reading: dict) -> bool:
    """Insère une mesure brute dans bronze.raw_readings (ignore les doublons).

    Le payload JSONB est le merge site + reading, enrichi d'un champ
    ``_site`` contenant les métadonnées du site au moment de la collecte
    (capacity_kw, site_name, site_type, location, status). clean.py lira
    ces infos directement depuis payload sans jointure.

    Returns:
        True si la ligne a été insérée, False si doublon ignoré.
    """
    site_id = site.get("id") or site.get("site_id")

    # Normalise le timestamp — l'API peut renvoyer ISO 8601 avec ou sans Z
    raw_ts = reading.get("timestamp")
    try:
        ts = datetime.fromisoformat(str(raw_ts))
    except (ValueError, TypeError):
        ts = datetime.now(tz=timezone.utc)

    # Payload = reading brut + métadonnées du site dénormalisées sous _site
    payload = {
        **reading,
        "_site": {
            "site_id":    site_id,
            "site_name":  site.get("name") or site.get("site_name", ""),
            "site_type":  site.get("type") or site.get("site_type", "office"),
            "capacity_kw": int(site.get("capacity_kw", 0)),
            "location":   site.get("location"),
            "status":     site.get("status", "active"),
        },
    }

    data_quality = _quality_from_reading(reading)

    sql = text("""
        INSERT INTO bronze.raw_readings (site_id, timestamp, data_quality, payload)
        VALUES (:site_id, :timestamp, :data_quality, :payload)
        ON CONFLICT (site_id, timestamp) DO NOTHING
    """)

    with get_engine().begin() as conn:
        result = conn.execute(sql, {
            "site_id":      site_id,
            "timestamp":    ts,
            "data_quality": data_quality,
            "payload":      json.dumps(payload),
        })
        return result.rowcount > 0


def run() -> dict[str, int]:
    """Point d'entrée : collecte et insère la dernière mesure de chaque site."""
    logger.info("[COLLECT] Démarrage")

    sites = get_sites()
    if not sites:
        logger.warning("[COLLECT] Aucun site récupéré — API Mock inaccessible ?")
        return {"sites": 0, "readings_inserted": 0, "readings_skipped": 0}

    logger.info("[COLLECT] %d site(s) récupérés", len(sites))

    inserted = skipped = 0
    for site in sites:
        site_id = site.get("id") or site.get("site_id")
        reading = get_current_reading(site_id)
        if reading is None:
            logger.warning("[COLLECT] Pas de mesure pour site %s", site_id)
            continue
        if _insert_reading(site, reading):
            inserted += 1
        else:
            skipped += 1  # doublon (déjà dans bronze)

    logger.info(
        "[COLLECT] Mesures : %d insérées, %d doublons ignorés", inserted, skipped
    )
    return {"sites": len(sites), "readings_inserted": inserted, "readings_skipped": skipped}


def bootstrap(hours: int = 24) -> dict[str, int]:
    """Amorçage initial : importe les `hours` dernières heures depuis l'API Mock.

    À appeler une seule fois au premier démarrage du container ETL (avant le
    cron). Tire l'historique par site via GET /api/v1/readings et insère
    toutes les mesures dans Bronze, en ignorant les doublons.

    Le MOOC limite à 1 000 résultats par appel ; on itère site par site pour
    rester sous ce seuil (7 sites × ~60 min × 24h = 10 080 mesures max,
    soit ~1 440 par site).

    Args:
        hours: Fenêtre temporelle à récupérer (défaut 24h).

    Returns:
        Dictionnaire avec les compteurs : sites traités, mesures insérées,
        mesures ignorées (doublons déjà présents dans Bronze).
    """
    logger.info("[BOOTSTRAP] Démarrage — historique des %dh passées", hours)

    sites = get_sites()
    if not sites:
        logger.warning("[BOOTSTRAP] Aucun site récupéré — API Mock inaccessible ?")
        return {"sites": 0, "readings_inserted": 0, "readings_skipped": 0}

    # Index site_id → dict site pour enrichir les readings de l'historique
    sites_by_id = {
        (s.get("id") or s.get("site_id")): s
        for s in sites
    }

    end_time   = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    total_inserted = total_skipped = 0

    for site in sites:
        site_id = site.get("id") or site.get("site_id")
        readings = get_readings_history(
            site_id=site_id,
            start_time=start_time,
            end_time=end_time,
            limit=1000,
        )
        logger.info("[BOOTSTRAP] site=%s → %d mesures récupérées", site_id, len(readings))

        for reading in readings:
            # Récupère le dict site correspondant (fallback sur le site courant)
            reading_site_id = reading.get("site_id", site_id)
            site_dict = sites_by_id.get(reading_site_id, site)
            if _insert_reading(site_dict, reading):
                total_inserted += 1
            else:
                total_skipped += 1

    logger.info(
        "[BOOTSTRAP] Terminé — %d insérées, %d doublons ignorés",
        total_inserted, total_skipped,
    )
    return {
        "sites":             len(sites),
        "readings_inserted": total_inserted,
        "readings_skipped":  total_skipped,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()