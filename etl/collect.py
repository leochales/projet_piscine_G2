"""ETL — Couche Bronze (amorçage).

bootstrap() :
  1. Seede automatiquement ``app.client`` + ``app.site`` depuis l'API Mock
     (idempotent : les sites déjà déclarés ne sont pas touchés).
  2. Récupère les mesures manquantes via GET /api/v1/readings et les insère
     dans ``bronze.raw_readings``. Chargement incrémental :
       - start_time = max(horodatage) déjà en base pour le site (watermark),
         ou NOW() − 24 h si la base est vide pour ce site ;
       - pas de end_time (l'API utilise son horloge).
     → idempotent, rattrape automatiquement un trou de collecte.

Codes de sortie :
  0 : au moins un site a répondu
  1 : tous les sites ont échoué (API Mock inaccessible, 400/500, timeout…)

À appeler une seule fois au premier démarrage du container ETL, puis le cron
collecte les nouvelles mesures chaque minute. Doublons bronze ignorés par
ON CONFLICT.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime, timedelta

import requests
from sqlalchemy import text

from common.db import get_engine
from etl.api_client import get_readings_history, get_sites

logger = logging.getLogger(__name__)

# Client propriétaire par défaut des sites seedés depuis l'API Mock
DEFAULT_CLIENT_NAME = "Démo EnerVision"

# Fenêtre maximale remontée quand aucune mesure n'est encore en base pour
# un site (pas de watermark à utiliser).
DEFAULT_BACKFILL_HOURS = 24

# Limite par appel à l'API Mock. Quand une réponse contient exactement ce
# nombre, les données sont probablement tronquées : on logge un warning.
API_PAGE_LIMIT = 1000

# Au-delà de ce lag, on considère un site comme « rassis » et on logge un
# warning à la fin du bootstrap.
STALE_THRESHOLD = timedelta(minutes=10)


def _seed_app_site_from_api(sites: list[dict]) -> dict[str, dict]:
    """Seed ``app.client`` + ``app.site`` depuis la liste renvoyée par l'API Mock.

    Idempotent : les sites déjà présents sont ignorés (ON CONFLICT DO NOTHING).
    Retourne un dict ``id_site`` → ``{capacite_kw, statut}`` de tous les sites
    déclarés en base (seedés + préexistants).
    """
    sql_get_client = text("SELECT id_client FROM app.client WHERE nom = :nom LIMIT 1")
    sql_insert_client = text(
        "INSERT INTO app.client (nom) VALUES (:nom) "
        "ON CONFLICT (nom) DO NOTHING RETURNING id_client"
    )
    sql_insert_site = text("""
        INSERT INTO app.site (
            id_site, id_client, nom, type, localisation, capacite_kw
        )
        VALUES (:id_site, :id_client, :nom, :type, :localisation, :capacite_kw)
        ON CONFLICT (id_site) DO NOTHING
    """)
    sql_known = text("SELECT id_site, capacite_kw, statut FROM app.site")

    inserted_sites = 0
    with get_engine().begin() as conn:
        # 1. Trouver (ou créer) le client propriétaire par défaut
        row = conn.execute(sql_get_client, {"nom": DEFAULT_CLIENT_NAME}).fetchone()
        if row is None:
            new_id = conn.execute(
                sql_insert_client, {"nom": DEFAULT_CLIENT_NAME}
            ).scalar()
            id_client = new_id
        else:
            id_client = row.id_client

        # 2. Seeder chaque site retourné par l'API Mock
        for site in sites:
            id_site = site.get("id") or site.get("site_id")
            if not id_site:
                continue
            # capacite_kw est obligatoire (CHECK > 0). On skip plutôt que
            # d'envoyer 0 qui violerait la contrainte et avorterait la
            # transaction entière.
            capacite_kw = site.get("capacity_kw")
            if not capacite_kw or capacite_kw <= 0:
                logger.warning(
                    "[BOOTSTRAP] site %s ignoré : capacity_kw manquante ou nulle",
                    id_site,
                )
                continue
            res = conn.execute(
                sql_insert_site,
                {
                    "id_site": id_site,
                    "id_client": id_client,
                    "nom": site.get("name") or site.get("site_name", id_site),
                    "type": site.get("type") or site.get("site_type", "office"),
                    "localisation": site.get("location"),
                    "capacite_kw": capacite_kw,
                },
            )
            inserted_sites += res.rowcount

        # 3. Charger la liste finale des sites connus
        known = {
            r.id_site: {"capacite_kw": float(r.capacite_kw), "statut": r.statut}
            for r in conn.execute(sql_known)
        }

    logger.info(
        "[BOOTSTRAP] Seed app.site : %d nouveau(x), %d site(s) connu(s) au total",
        inserted_sites,
        len(known),
    )
    return known


def _get_watermarks(id_sites: list[str]) -> dict[str, datetime | None]:
    """Retourne le max(horodatage) déjà en bronze pour chaque site.

    None quand aucune mesure n'est encore en base → l'appelant choisira
    un défaut (DEFAULT_BACKFILL_HOURS).
    """
    sql = text("""
        SELECT id_site, MAX(horodatage) AS watermark
        FROM bronze.raw_readings
        WHERE id_site = ANY(:ids)
        GROUP BY id_site
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"ids": id_sites}).fetchall()
    watermarks: dict[str, datetime | None] = {s: None for s in id_sites}
    for r in rows:
        watermarks[r.id_site] = r.watermark
    return watermarks


def _parse_iso_utc(raw: str) -> datetime | None:
    """Parse un timestamp ISO 8601, force UTC si naive, None si invalide."""
    try:
        ts = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _insert_reading(site: dict, reading: dict, known: dict[str, dict]) -> bool:
    """Insère une mesure brute dans bronze.raw_readings (ignore les doublons).

    Retourne False si le site est inconnu, ou si le timestamp est illisible,
    ou si c'est un doublon (ON CONFLICT).
    """
    id_site = site.get("id") or site.get("site_id")
    if id_site not in known:
        return False

    ts = _parse_iso_utc(reading.get("timestamp"))
    if ts is None:
        logger.warning(
            "[BOOTSTRAP] site %s : timestamp illisible, mesure ignorée (payload=%s)",
            id_site,
            reading.get("timestamp"),
        )
        return False

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


def _check_freshness(known: dict[str, dict]) -> None:
    """Logge un warning pour chaque site dont la dernière mesure est trop vieille."""
    if not known:
        return
    sql = text("""
        SELECT id_site, NOW() - MAX(horodatage) AS lag
        FROM bronze.raw_readings
        WHERE id_site = ANY(:ids)
        GROUP BY id_site
        HAVING NOW() - MAX(horodatage) > :threshold
    """)
    with get_engine().connect() as conn:
        stale = conn.execute(
            sql, {"ids": list(known), "threshold": STALE_THRESHOLD}
        ).fetchall()
    for row in stale:
        logger.warning(
            "[BOOTSTRAP] site %s : dernière mesure il y a %s", row.id_site, row.lag
        )


def bootstrap() -> dict[str, int]:
    """Amorçage : seede app.site puis importe les mesures manquantes par site.

    Chargement incrémental : part de max(horodatage) déjà en bronze pour
    chaque site, ou de NOW − 24 h si la base est vide pour ce site.
    """
    logger.info("[BOOTSTRAP] Démarrage — chargement incrémental")

    sites = get_sites()
    if not sites:
        logger.error("[BOOTSTRAP] Aucun site récupéré — API Mock inaccessible ?")
        return {"sites": 0, "readings_inserted": 0, "sites_in_error": 0}

    known = _seed_app_site_from_api(sites)
    if not known:
        logger.warning("[BOOTSTRAP] app.site vide après seed — rien à collecter")
        return {"sites": 0, "readings_inserted": 0, "sites_in_error": 0}

    sites_by_id = {(s.get("id") or s.get("site_id")): s for s in sites}
    watermarks = _get_watermarks(list(known))
    now_utc = datetime.now(tz=UTC)

    total_inserted = sites_in_error = 0

    for id_site in known:
        site = sites_by_id.get(id_site)
        if site is None:
            logger.warning(
                "[BOOTSTRAP] site %s déclaré en base mais absent de l'API Mock",
                id_site,
            )
            continue

        start_time = watermarks.get(id_site) or (
            now_utc - timedelta(hours=DEFAULT_BACKFILL_HOURS)
        )

        try:
            readings = get_readings_history(
                site_id=id_site,
                start_time=start_time,
                limit=API_PAGE_LIMIT,
            )
        except requests.RequestException as exc:
            logger.error("[BOOTSTRAP] site %s : échec API — %s", id_site, exc)
            sites_in_error += 1
            continue

        logger.info(
            "[BOOTSTRAP] site=%s depuis %s → %d mesures récupérées",
            id_site,
            start_time.isoformat(timespec="seconds"),
            len(readings),
        )
        if len(readings) == API_PAGE_LIMIT:
            logger.warning(
                "[BOOTSTRAP] site %s : %d mesures (limite API atteinte, données "
                "sans doute tronquées — relancer l'amorçage ou raccourcir la "
                "fenêtre)",
                id_site,
                API_PAGE_LIMIT,
            )

        for reading in readings:
            reading_site_id = reading.get("site_id", id_site)
            site_dict = sites_by_id.get(reading_site_id, site)
            if _insert_reading(site_dict, reading, known):
                total_inserted += 1

    _check_freshness(known)

    logger.info(
        "[BOOTSTRAP] Terminé — %d insérées, %d site(s) en erreur sur %d",
        total_inserted,
        sites_in_error,
        len(known),
    )

    # Si tous les sites ont échoué, on remonte un code non nul pour que
    # l'ordonnanceur (init container, CI, cron) détecte le problème.
    if sites_in_error == len(known) and sites_in_error > 0:
        logger.error("[BOOTSTRAP] Tous les sites ont échoué — exit 1")
        sys.exit(1)

    return {
        "sites": len(known),
        "readings_inserted": total_inserted,
        "sites_in_error": sites_in_error,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    bootstrap()
