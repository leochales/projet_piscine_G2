"""ETL — Dernière mesure et état des capteurs dans gold (SMARTOPS-23).

Deux mises à jour indépendantes, chaque minute :
  1. ``gold.derniere_mesure`` depuis silver, par la fonction SQL
     ``gold.mettre_a_jour_derniere_mesure()`` (db/13_gold_derniere_mesure.sql),
     testée en CI par db/tests/test_gold_derniere_mesure.sql. Seules les
     mesures transmises comptent, ni les trous de collecte ni les mesures
     « perte réseau » (que l'API Mock renvoie toutes à null) : un site qui ne
     transmet plus garde sa dernière mesure, dont l'horodatage vieillit ;
  2. ``gold.etat_capteur`` depuis GET /api/v1/sensors/status.

Si l'API Mock est injoignable ou renvoie une réponse invalide, l'état des
capteurs n'est pas modifié (il garde sa date ``mis_a_jour_le``), mais la
dernière mesure est quand même mise à jour.

Le bandeau « sites qui ne transmettent plus » du dashboard lit la vue
``gold.etat_site``, calculée à la lecture. Elle distingue un site muet d'une
collecte interrompue (ETL arrêté, API Mock injoignable) : dans ce cas,
``collecte_a_jour`` est faux et ``transmet`` inconnu (NULL) pour tous les sites.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from pydantic import ValidationError
from sqlalchemy import Connection, text

from common.db import get_engine
from common.logs import configure_logging
from etl.api_client import get_sensor_status
from etl.collect import load_declared_sites
from etl.schemas import SiteSensors

logger = logging.getLogger(__name__)


def update_latest_reading(conn: Connection) -> int:
    """Met à jour gold.derniere_mesure. Retourne le nombre de sites mis à jour."""
    return conn.execute(
        text("SELECT gold.mettre_a_jour_derniere_mesure()")
    ).scalar_one()


def parse_sensor_status(payload: Any, declared: set[str]) -> list[dict[str, Any]]:
    """Réponse de /sensors/status → lignes de gold.etat_capteur.

    Seuls les sites déclarés dans app.site sont gardés (clé étrangère). Un site
    dont la description est invalide est ignoré avec un avertissement, sans
    empêcher la mise à jour des autres.
    """
    if not isinstance(payload, dict):
        logger.warning(
            "sensors/status : réponse inattendue (%s)", type(payload).__name__
        )
        return []

    rows: list[dict[str, Any]] = []
    for id_site, raw in payload.items():
        if id_site not in declared:
            continue
        try:
            site = SiteSensors.model_validate(raw)
        except ValidationError as exc:
            logger.warning("sensors/status : site=%s ignoré, %s", id_site, exc)
            continue
        rows.extend(
            {
                "id_site": id_site,
                "capteur": capteur,
                "statut": state.status,
                # Une date de rétablissement n'a de sens que pour un capteur en panne
                "en_panne_jusqu_a": (
                    state.failing_until if state.status == "failing" else None
                ),
            }
            for capteur, state in sorted(site.sensors.items())
        )
    return rows


def upsert_sensor_status(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Remplace l'état des capteurs reçus (un capteur absent garde son état)."""
    sql = text("""
        INSERT INTO gold.etat_capteur (
            id_site, capteur, statut, en_panne_jusqu_a, mis_a_jour_le
        )
        VALUES (:id_site, :capteur, :statut, :en_panne_jusqu_a, now())
        ON CONFLICT (id_site, capteur) DO UPDATE SET
            statut = excluded.statut,
            en_panne_jusqu_a = excluded.en_panne_jusqu_a,
            mis_a_jour_le = excluded.mis_a_jour_le
    """)
    conn.execute(sql, rows)


def update() -> dict[str, int]:
    """Met à jour la dernière mesure, puis l'état des capteurs."""
    engine = get_engine()
    with engine.begin() as conn:
        sites_updated = update_latest_reading(conn)
        declared = set(load_declared_sites(conn))
    logger.info("dernière mesure : %d site(s) mis à jour", sites_updated)

    try:
        payload = get_sensor_status()
    except requests.RequestException as exc:
        # État des capteurs inchangé : sa date mis_a_jour_le montre son âge
        logger.warning(
            "sensors/status injoignable, état des capteurs inchangé : %s", exc
        )
        return {"sites_updated": sites_updated, "sensors_updated": 0}

    rows = parse_sensor_status(payload, declared)
    if rows:
        with engine.begin() as conn:
            upsert_sensor_status(conn, rows)
    failing = sorted(
        {f"{r['id_site']}/{r['capteur']}" for r in rows if r["statut"] == "failing"}
    )
    # info et non warning : l'API Mock simule des pannes en permanence
    logger.info(
        "état des capteurs : %d capteur(s), en panne : %s",
        len(rows),
        ", ".join(failing) or "aucun",
    )
    return {"sites_updated": sites_updated, "sensors_updated": len(rows)}


if __name__ == "__main__":
    configure_logging("etl")
    update()
