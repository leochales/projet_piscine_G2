"""ETL — Amorçage d'une base neuve depuis l'historique simulé (SMARTOPS-22).

Commande à part, hors de la collecte minute :

    python -m etl.bootstrap

Lancée au démarrage du conteneur ETL, avant le cron (voir etl/Dockerfile),
et rejouable à la main. Seuls les sites sans aucune mesure en bronze sont
amorcés : on charge les 7 derniers jours (BOOTSTRAP_DEPTH) via
GET /api/v1/readings, à la minute, pour que silver, gold et le dashboard aient
des données dès le premier démarrage. /current prend ensuite le relais
(``etl.collect``). Un site qui a déjà des mesures n'est jamais réamorcé :
une rétention partielle de bronze ne déclenche rien, et la collecte minute
n'attend jamais l'amorçage.

/readings tire de nouvelles valeurs à chaque appel : il n'est utilisé ni pour
la collecte minute ni pour combler un trou après une coupure, qui doit rester
visible. Les mesures d'amorçage portent ``"_source": "readings_amorcage"``
dans leur payload (silver ignore cette clé).

Grille de 60 s : l'API renvoie toujours ``limit`` points répartis sur la
fenêtre demandée (pas = (end − start) / limit, fin exclue). On choisit donc
des bornes alignées sur la minute et ``limit`` = nombre de minutes, pour
obtenir des horodatages hh:mm:00.

Codes de sortie :
  0 : rien à amorcer, ou au moins un site amorcé
  1 : tous les sites à amorcer ont échoué
"""

from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text

from common.db import get_engine
from common.logs import configure_logging
from etl.api_client import READINGS_MAX_LIMIT, get_readings_history
from etl.collect import load_declared_sites
from etl.grid import STEP, floor_to_step, to_utc
from etl.schemas import ReadingKey

logger = logging.getLogger(__name__)

# Profondeur chargée pour un site sans aucune mesure en base : 7 jours, la
# plus longue période affichée par le dashboard (vue site « 7 jours », coût
# et CO₂ sur 7 jours). Soit 11 appels /readings par site.
BOOTSTRAP_DEPTH = timedelta(days=7)

# L'horloge de l'API Mock retarde d'une trentaine de secondes : demander des
# données jusqu'à « maintenant » renvoie un 400 (« données dans le futur »).
SAFETY_LAG = timedelta(minutes=2)

# Marqueur ajouté au payload des mesures d'amorçage
SOURCE_KEY = "_source"
SOURCE_BOOTSTRAP = "readings_amorcage"

EXIT_ALL_SITES_FAILED = 1


@dataclass(frozen=True)
class Window:
    """Fenêtre [start, end[ à demander à l'API, avec ``limit`` points."""

    start: datetime
    end: datetime
    limit: int


def plan_windows(slot: datetime) -> list[Window]:
    """Découpe l'amorçage en fenêtres d'au plus READINGS_MAX_LIMIT minutes.

    ``slot`` est la minute (UTC) du lancement. La période va de
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
    """Récupère l'historique d'amorçage d'un site, marqué ``_source``.

    Lève requests.RequestException si un appel échoue.
    """
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for window in plan_windows(slot):
        readings = get_readings_history(
            site_id=id_site,
            start_time=window.start,
            end_time=window.end,
            limit=window.limit,
        )
        rows += [
            (ts, {**payload, SOURCE_KEY: SOURCE_BOOTSTRAP})
            for ts, payload in select_readings(id_site, window, readings)
        ]
    return rows


def sites_to_bootstrap(conn: Connection, id_sites: list[str]) -> list[str]:
    """Sites sans aucune mesure en bronze (un EXISTS par site, via l'index)."""
    sql = text("""
        SELECT s.id_site
        FROM unnest(CAST(:ids AS varchar[])) AS s (id_site)
        WHERE NOT EXISTS (
            SELECT 1 FROM bronze.raw_readings AS b WHERE b.id_site = s.id_site
        )
        ORDER BY s.id_site
    """)
    return [r.id_site for r in conn.execute(sql, {"ids": id_sites})]


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


def bootstrap(now: datetime | None = None) -> dict[str, int]:
    """Amorce les sites actifs qui n'ont encore aucune mesure en bronze."""
    slot = floor_to_step(to_utc(now or datetime.now(tz=UTC)))

    with get_engine().connect() as conn:
        declared = load_declared_sites(conn)
        todo = sites_to_bootstrap(conn, list(declared)) if declared else []
    if not todo:
        logger.info("amorçage : aucun site sans mesure, rien à faire")
        return {"sites": 0, "readings_inserted": 0, "sites_in_error": 0}

    with ThreadPoolExecutor(max_workers=len(todo)) as pool:
        futures = {s: pool.submit(fetch_history, s, slot) for s in todo}

    total_inserted = sites_in_error = 0
    for id_site, future in futures.items():
        try:
            rows = future.result()
            with get_engine().begin() as conn:
                n = insert_history(conn, id_site, rows)
        except Exception:
            # /readings en 4xx/5xx, base indisponible… : le site reste vide et
            # sera amorcé au prochain lancement s'il n'a toujours aucune mesure
            logger.exception("site %s : échec de l'amorçage", id_site)
            sites_in_error += 1
            continue
        total_inserted += n
        logger.info("site=%s : amorçage, %d mesure(s) /readings insérée(s)", id_site, n)

    logger.info(
        "amorçage terminé — %d insérées, %d site(s) en erreur sur %d",
        total_inserted,
        sites_in_error,
        len(todo),
    )
    if sites_in_error == len(todo):
        sys.exit(EXIT_ALL_SITES_FAILED)
    return {
        "sites": len(todo),
        "readings_inserted": total_inserted,
        "sites_in_error": sites_in_error,
    }


if __name__ == "__main__":
    configure_logging("etl")
    bootstrap()
