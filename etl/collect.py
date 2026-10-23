"""ETL — Collecte des mesures dans la couche bronze.

collect() :
  1. Lit dans ``app.site`` les sites actifs à collecter. L'ETL n'écrit jamais
     dans ``app`` : les sites sont déclarés par l'application
     (``db/08_sites_demo.sql`` pour la démo). Les sites de l'API Mock non
     déclarés sont ignorés et signalés dans les logs.
  2. Pour chaque site, récupère les mesures manquantes via GET
     /api/v1/readings et les insère dans ``bronze.raw_readings``.

Grille fixe de 60 s : l'API renvoie toujours ``limit`` points répartis sur
la fenêtre demandée (pas = (end − start) / limit, fin exclue). On choisit
donc des bornes alignées sur la minute et ``limit`` = nombre de minutes, pour
obtenir des horodatages déterministes (hh:mm:00). La contrainte
UNIQUE (id_site, horodatage) de bronze rend alors la collecte idempotente.

Appelable à chaque minute comme au premier démarrage : sans mesure en base,
on remonte DEFAULT_BACKFILL ; après une coupure, on rattrape au plus
MAX_BACKFILL.

Codes de sortie :
  0 : au moins un site a répondu
  1 : tous les sites ont échoué (API Mock inaccessible, 400/500, timeout…)
  2 : aucun site actif déclaré dans app.site
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from pydantic import ValidationError
from sqlalchemy import Connection, text

from common.db import get_engine
from etl.api_client import READINGS_MAX_LIMIT, get_readings_history, get_sites
from etl.schemas import ReadingKey, SiteInfo

logger = logging.getLogger(__name__)

# Pas de la grille de mesures
STEP = timedelta(seconds=60)

# L'horloge de l'API Mock retarde d'une vingtaine de secondes : demander
# des données jusqu'à « maintenant » renvoie un 400 (« données dans le futur »).
SAFETY_LAG = timedelta(minutes=2)

# Profondeur remontée pour un site sans aucune mesure en base
DEFAULT_BACKFILL = timedelta(hours=24)

# Rattrapage maximal après une coupure, pour borner le nombre d'appels
MAX_BACKFILL = timedelta(days=7)

# Au-delà de ce retard, un site est considéré comme « rassis »
STALE_THRESHOLD = timedelta(minutes=10)

# Écart de capacité toléré entre app.site et l'API Mock avant de le signaler
CAPACITY_TOLERANCE = 0.01

EXIT_ALL_SITES_FAILED = 1
EXIT_NO_DECLARED_SITE = 2


@dataclass(frozen=True)
class Window:
    """Fenêtre [start, end[ à demander à l'API, avec ``limit`` points."""

    start: datetime
    end: datetime
    limit: int


def floor_to_step(ts: datetime) -> datetime:
    """Arrondit à la minute inférieure, en UTC."""
    ts = ts.astimezone(UTC)
    return ts.replace(second=0, microsecond=0)


def plan_windows(watermark: datetime | None, now: datetime) -> list[Window]:
    """Découpe la période à collecter en fenêtres alignées sur la grille.

    ``watermark`` est le dernier horodatage déjà en bronze pour le site (ou
    None). La période va de la minute qui suit le watermark jusqu'à
    ``now − SAFETY_LAG``, tronquée à MAX_BACKFILL. Chaque fenêtre couvre au
    plus READINGS_MAX_LIMIT minutes.
    """
    last = floor_to_step(now - SAFETY_LAG)
    if watermark is None:
        first = last - DEFAULT_BACKFILL
    else:
        # floor puis + STEP : un watermark hors grille (ancienne collecte)
        # repart sur la minute pleine suivante
        first = max(floor_to_step(watermark) + STEP, last - MAX_BACKFILL)

    windows: list[Window] = []
    while first <= last:
        remaining = (last - first) // STEP + 1
        n = min(remaining, READINGS_MAX_LIMIT)
        windows.append(Window(start=first, end=first + n * STEP, limit=n))
        first += n * STEP
    return windows


def select_readings(
    id_site: str, window: Window, readings: list[dict[str, Any]]
) -> tuple[list[tuple[datetime, dict[str, Any]]], int]:
    """Garde les mesures du site qui tombent sur la grille de la fenêtre.

    Retourne les couples (horodatage UTC, payload brut) et le nombre de
    mesures écartées (clé illisible, autre site, hors grille).
    """
    kept: list[tuple[datetime, dict[str, Any]]] = []
    rejected = 0
    for reading in readings:
        try:
            key = ReadingKey.model_validate(reading)
        except ValidationError as exc:
            logger.warning(
                "site %s : mesure sans clé valide écartée (%s)",
                id_site,
                exc.errors(include_url=False),
            )
            rejected += 1
            continue
        on_grid = window.start <= key.timestamp < window.end and (
            key.timestamp - window.start
        ) % STEP == timedelta(0)
        if key.site_id != id_site or not on_grid:
            logger.warning(
                "site %s : mesure inattendue écartée (site=%s, horodatage=%s)",
                id_site,
                key.site_id,
                key.timestamp.isoformat(),
            )
            rejected += 1
            continue
        kept.append((key.timestamp, reading))
    return kept, rejected


def check_sites_consistency(
    declared: dict[str, float], mock_sites: list[SiteInfo]
) -> list[str]:
    """Compare app.site à l'API Mock. Retourne les écarts à signaler."""
    issues: list[str] = []
    mock = {s.site_id: s for s in mock_sites}
    for id_site in sorted(mock.keys() - declared.keys()):
        issues.append(f"site {id_site} présent dans l'API Mock mais non déclaré")
    for id_site in sorted(declared.keys() - mock.keys()):
        issues.append(f"site {id_site} déclaré mais absent de l'API Mock")
    for id_site in sorted(declared.keys() & mock.keys()):
        ours, theirs = declared[id_site], mock[id_site].capacity_kw
        if abs(ours - theirs) > CAPACITY_TOLERANCE * theirs:
            issues.append(
                f"site {id_site} : capacité {ours} kW en base, {theirs} kW dans l'API Mock"
            )
    return issues


def load_declared_sites(conn: Connection) -> dict[str, float]:
    """Sites actifs de app.site → capacité en kW (lecture seule)."""
    sql = text(
        "SELECT id_site, capacite_kw FROM app.site "
        "WHERE statut = 'active' ORDER BY id_site"
    )
    return {r.id_site: float(r.capacite_kw) for r in conn.execute(sql)}


def get_watermarks(conn: Connection, id_sites: list[str]) -> dict[str, datetime | None]:
    """Dernier horodatage en bronze pour chaque site (None si aucun)."""
    sql = text("""
        SELECT id_site, MAX(horodatage) AS watermark
        FROM bronze.raw_readings
        WHERE id_site = ANY(:ids)
        GROUP BY id_site
    """)
    watermarks: dict[str, datetime | None] = dict.fromkeys(id_sites)
    for r in conn.execute(sql, {"ids": id_sites}):
        watermarks[r.id_site] = r.watermark
    return watermarks


def insert_bronze(
    conn: Connection, id_site: str, rows: list[tuple[datetime, dict[str, Any]]]
) -> int:
    """Insère un lot de mesures brutes en un seul aller-retour.

    Les doublons (même site, même horodatage) sont ignorés : la première
    valeur reçue est conservée, l'API Mock tirant de nouvelles valeurs à
    chaque appel. Retourne le nombre de lignes réellement insérées.
    """
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


def log_stale_sites(conn: Connection, id_sites: list[str]) -> None:
    """Logge un warning pour chaque site dont la dernière mesure est trop vieille."""
    sql = text("""
        SELECT id_site, NOW() - MAX(horodatage) AS lag
        FROM bronze.raw_readings
        WHERE id_site = ANY(:ids)
        GROUP BY id_site
        HAVING NOW() - MAX(horodatage) > :threshold
    """)
    for row in conn.execute(sql, {"ids": id_sites, "threshold": STALE_THRESHOLD}):
        logger.warning("site %s : dernière mesure il y a %s", row.id_site, row.lag)


def _warn_on_inconsistent_sites(declared: dict[str, float]) -> None:
    """Contrôle de cohérence avec l'API Mock, sans effet sur la collecte."""
    try:
        mock_sites = get_sites()
    except (requests.RequestException, ValidationError) as exc:
        logger.warning("contrôle des sites impossible (GET /sites) : %s", exc)
        return
    for issue in check_sites_consistency(declared, mock_sites):
        logger.warning(issue)


def collect_site(id_site: str, watermark: datetime | None, now: datetime) -> int:
    """Collecte un site, fenêtre par fenêtre. Retourne le nombre d'insertions.

    Lève requests.RequestException si l'API échoue : les fenêtres déjà
    insérées restent acquises, la suivante repartira du nouveau watermark.
    """
    inserted = 0
    for window in plan_windows(watermark, now):
        readings = get_readings_history(
            site_id=id_site,
            start_time=window.start,
            end_time=window.end,
            limit=window.limit,
        )
        rows, rejected = select_readings(id_site, window, readings)
        with get_engine().begin() as conn:
            n = insert_bronze(conn, id_site, rows)
        inserted += n
        logger.info(
            "site=%s [%s, %s[ : %d reçues, %d insérées, %d écartées",
            id_site,
            window.start.isoformat(timespec="minutes"),
            window.end.isoformat(timespec="minutes"),
            len(readings),
            n,
            rejected,
        )
    return inserted


def collect(now: datetime | None = None) -> dict[str, int]:
    """Collecte incrémentale de tous les sites actifs déclarés."""
    now = now or datetime.now(tz=UTC)

    with get_engine().connect() as conn:
        declared = load_declared_sites(conn)
        if not declared:
            logger.error(
                "aucun site actif dans app.site : rien à collecter "
                "(déclarer les sites, voir db/08_sites_demo.sql)"
            )
            sys.exit(EXIT_NO_DECLARED_SITE)
        watermarks = get_watermarks(conn, list(declared))

    _warn_on_inconsistent_sites(declared)

    total_inserted = sites_in_error = 0
    for id_site in declared:
        try:
            total_inserted += collect_site(id_site, watermarks[id_site], now)
        except requests.RequestException as exc:
            logger.error("site %s : échec API — %s", id_site, exc)
            sites_in_error += 1

    with get_engine().connect() as conn:
        log_stale_sites(conn, list(declared))

    logger.info(
        "collecte terminée — %d insérées, %d site(s) en erreur sur %d",
        total_inserted,
        sites_in_error,
        len(declared),
    )

    # Tous les sites en échec : code non nul pour que l'ordonnanceur le voie
    if sites_in_error == len(declared):
        logger.error("tous les sites ont échoué — exit %d", EXIT_ALL_SITES_FAILED)
        sys.exit(EXIT_ALL_SITES_FAILED)

    return {
        "sites": len(declared),
        "readings_inserted": total_inserted,
        "sites_in_error": sites_in_error,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    collect()
