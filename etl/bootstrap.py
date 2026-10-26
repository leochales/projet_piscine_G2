"""ETL — Amorçage d'une base neuve depuis l'historique simulé (SMARTOPS-22).

Un site sans aucune mesure en bronze est amorcé une seule fois : on charge
les BOOTSTRAP_DEPTH dernières heures via GET /api/v1/readings, à la minute,
pour que silver, gold et le dashboard aient des données dès le premier
démarrage. /current prend ensuite le relais (``etl.collect``).

/readings tire de nouvelles valeurs à chaque appel : il n'est utilisé ni pour
la collecte minute ni pour combler un trou après une coupure, qui doit rester
visible. Les mesures d'amorçage restent reconnaissables en bronze : leur
horodatage API est en « …Z », celui de /current n'a pas de fuseau.

Grille de 60 s : l'API renvoie toujours ``limit`` points répartis sur la
fenêtre demandée (pas = (end − start) / limit, fin exclue). On choisit donc
des bornes alignées sur la minute et ``limit`` = nombre de minutes, pour
obtenir des horodatages hh:mm:00.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text

from etl.api_client import READINGS_MAX_LIMIT, get_readings_history
from etl.schemas import ReadingKey

logger = logging.getLogger(__name__)

STEP = timedelta(seconds=60)

# Profondeur chargée pour un site sans aucune mesure en base
BOOTSTRAP_DEPTH = timedelta(hours=24)

# L'horloge de l'API Mock retarde d'une trentaine de secondes : demander des
# données jusqu'à « maintenant » renvoie un 400 (« données dans le futur »).
SAFETY_LAG = timedelta(minutes=2)


@dataclass(frozen=True)
class Window:
    """Fenêtre [start, end[ à demander à l'API, avec ``limit`` points."""

    start: datetime
    end: datetime
    limit: int


def plan_windows(slot: datetime) -> list[Window]:
    """Découpe l'amorçage en fenêtres d'au plus READINGS_MAX_LIMIT minutes.

    ``slot`` est la minute (UTC) du passage en cours. La période va de
    ``slot − BOOTSTRAP_DEPTH`` à ``slot − SAFETY_LAG`` (exclue) ; les minutes
    restantes sont collectées par /current ou imputées en silver.
    """
    first = slot - BOOTSTRAP_DEPTH
    end = slot - SAFETY_LAG
    windows: list[Window] = []
    while first < end:
        n = min((end - first) // STEP, READINGS_MAX_LIMIT)
        windows.append(Window(start=first, end=first + n * STEP, limit=n))
        first += n * STEP
    return windows


def select_readings(
    id_site: str, window: Window, readings: list[dict[str, Any]]
) -> list[tuple[datetime, dict[str, Any]]]:
    """Garde les mesures du site qui tombent sur la grille de la fenêtre."""
    kept: list[tuple[datetime, dict[str, Any]]] = []
    for reading in readings:
        try:
            key = ReadingKey.model_validate(reading)
        except ValidationError:
            continue
        on_grid = window.start <= key.timestamp < window.end and (
            key.timestamp - window.start
        ) % STEP == timedelta(0)
        if key.site_id == id_site and on_grid:
            kept.append((key.timestamp, reading))
    rejected = len(readings) - len(kept)
    if rejected:
        logger.warning(
            "site %s : %d mesure(s) d'amorçage écartée(s) (clé illisible, "
            "autre site ou hors grille)",
            id_site,
            rejected,
        )
    return kept


def fetch_history(
    id_site: str, slot: datetime
) -> list[tuple[datetime, dict[str, Any]]]:
    """Récupère l'historique d'amorçage d'un site.

    Lève requests.RequestException si un appel échoue : rien n'est alors
    inséré et l'amorçage sera retenté au passage suivant.
    """
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for window in plan_windows(slot):
        readings = get_readings_history(
            site_id=id_site,
            start_time=window.start,
            end_time=window.end,
            limit=window.limit,
        )
        rows += select_readings(id_site, window, readings)
    return rows


def sites_to_bootstrap(conn: Connection, id_sites: list[str]) -> set[str]:
    """Sites sans aucune mesure en bronze."""
    sql = text("""
        SELECT DISTINCT id_site FROM bronze.raw_readings WHERE id_site = ANY(:ids)
    """)
    present = {r.id_site for r in conn.execute(sql, {"ids": id_sites})}
    return set(id_sites) - present


def insert_history(
    conn: Connection, id_site: str, rows: list[tuple[datetime, dict[str, Any]]]
) -> int:
    """Insère l'historique en un seul aller-retour. Retourne le nombre inséré."""
    if not rows:
        return 0
    sql = text("""
        INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
        SELECT :id_site, t.horodatage, t.payload
        FROM unnest(
            CAST(:horodatages AS timestamptz[]),
            CAST(:payloads AS jsonb[])
        ) AS t (horodatage, payload)
        ON CONFLICT (id_site, horodatage) DO NOTHING
        RETURNING id
    """)
    result = conn.execute(
        sql,
        {
            "id_site": id_site,
            "horodatages": [ts for ts, _ in rows],
            "payloads": [json.dumps(payload) for _, payload in rows],
        },
    )
    return len(result.fetchall())
