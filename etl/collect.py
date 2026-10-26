"""ETL — Collecte des mesures dans la couche bronze.

collect() :
  1. Lit dans ``app.site`` les sites actifs à collecter. L'ETL n'écrit jamais
     dans ``app`` : les sites sont déclarés par l'application
     (``db/08_sites_demo.sql`` pour la démo). Les sites de l'API Mock non
     déclarés sont ignorés et signalés dans les logs.
  2. Pour chaque site, lit la mesure instantanée via
     GET /api/v1/sites/{site_id}/current et l'insère dans
     ``bronze.raw_readings``.

Lancé toutes les minutes. /current est la seule source temps réel de l'API
Mock (pannes capteurs, pics simulés). /api/v1/readings tire au contraire un
historique aléatoire, différent à chaque appel : il ne sert qu'à l'amorçage
d'une base neuve (``etl.bootstrap``, lancé à part), jamais à la collecte
minute ni à combler un trou (sinon bronze contient des valeurs inventées et
les vraies coupures sont masquées).

Grille de 60 s : la clé de bronze est la minute pleine (UTC) du passage,
prise sur notre horloge. L'horodatage de /current n'est pas utilisé pour la
clé : l'horloge de l'API Mock retarde d'environ 31 s, si bien qu'un passage
lancé à hh:mm:00 par le cron tombe tantôt dans la minute précédente, tantôt
dans la courante selon le temps de démarrage, ce qui créerait doublons et
trous. Le payload brut, avec son horodatage exact, est conservé tel quel.
La contrainte UNIQUE (id_site, horodatage) rend la collecte idempotente : deux passages
dans la même minute ne gardent que la première mesure. Une minute sans
passage reste un trou, que silver rend visible (``no_reading``) et impute
s'il est court.

Codes de sortie :
  0 : au moins un site a répondu
  1 : tous les sites ont échoué (API Mock inaccessible, 4xx/5xx, timeout…)
  2 : aucun site actif déclaré dans app.site
"""

from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from pydantic import ValidationError
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from common.db import get_engine
from common.logs import configure_logging
from etl.api_client import get_current_reading, get_sites
from etl.grid import floor_to_step, to_utc
from etl.schemas import ReadingKey, SiteInfo

logger = logging.getLogger(__name__)

# Écart maximal toléré entre l'horodatage de la mesure et notre horloge.
# L'horloge de l'API Mock retarde d'environ 31 s ; au-delà de ce seuil, la
# mesure n'est pas « actuelle » et elle est écartée.
MAX_CLOCK_SKEW = timedelta(minutes=5)

# Au-delà de ce retard, un site est considéré comme « rassis »
STALE_THRESHOLD = timedelta(minutes=10)

# Écart de capacité toléré entre app.site et l'API Mock avant de le signaler
CAPACITY_TOLERANCE = 0.01

EXIT_ALL_SITES_FAILED = 1
EXIT_NO_DECLARED_SITE = 2


class ReadingRejected(Exception):
    """Réponse de /current inutilisable (clé illisible, autre site, horodatage aberrant)."""


def reading_slot(id_site: str, reading: dict[str, Any], now: datetime) -> datetime:
    """Minute de la grille (UTC) à laquelle ranger une mesure de /current.

    C'est la minute de ``now`` (début du passage), pas celle de l'horodatage
    de l'API, décalé (voir l'en-tête du module).

    Lève ReadingRejected si la clé est illisible, si la mesure concerne un
    autre site ou si son horodatage est trop loin de ``now``.
    """
    try:
        key = ReadingKey.model_validate(reading)
    except ValidationError as exc:
        raise ReadingRejected(
            f"mesure sans clé valide ({exc.errors(include_url=False)})"
        ) from exc
    if key.site_id != id_site:
        raise ReadingRejected(f"mesure d'un autre site ({key.site_id})")
    if abs(key.timestamp - now) > MAX_CLOCK_SKEW:
        raise ReadingRejected(
            f"horodatage {key.timestamp.isoformat()} trop loin de {now.isoformat()}"
        )
    return floor_to_step(now)


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


def insert_bronze(
    conn: Connection, id_site: str, horodatage: datetime, payload: dict[str, Any]
) -> bool:
    """Insère une mesure brute. Retourne False si la minute était déjà collectée.

    En cas de doublon (même site, même minute), la première mesure reçue est
    conservée.
    """
    sql = text("""
        INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
        VALUES (:id_site, :horodatage, CAST(:payload AS jsonb))
        ON CONFLICT (id_site, horodatage) DO NOTHING
        RETURNING id
    """)
    result = conn.execute(
        sql,
        {"id_site": id_site, "horodatage": horodatage, "payload": json.dumps(payload)},
    )
    return result.first() is not None


def log_stale_sites(conn: Connection, id_sites: list[str]) -> None:
    """Logge un warning pour chaque site sans mesure récente, ou sans mesure du tout.

    La dernière mesure est lue site par site par l'index (id_site,
    horodatage), sans parcourir bronze.
    """
    sql = text("""
        SELECT s.id_site, now() - b.derniere AS lag
        FROM unnest(CAST(:ids AS varchar[])) AS s (id_site)
        LEFT JOIN LATERAL (
            SELECT max(r.horodatage) AS derniere
            FROM bronze.raw_readings AS r
            WHERE r.id_site = s.id_site
        ) AS b ON true
        WHERE b.derniere IS NULL OR now() - b.derniere > :threshold
        ORDER BY s.id_site
    """)
    for row in conn.execute(sql, {"ids": id_sites, "threshold": STALE_THRESHOLD}):
        if row.lag is None:
            logger.warning("site %s : aucune mesure en bronze", row.id_site)
        else:
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


def collect_site(id_site: str, reading: dict[str, Any], now: datetime) -> int:
    """Range en bronze la mesure /current d'un site. Retourne 1 si insérée, 0 sinon.

    Lève ReadingRejected si la mesure est inutilisable.
    """
    slot = reading_slot(id_site, reading, now)
    with get_engine().begin() as conn:
        inserted = insert_bronze(conn, id_site, slot, reading)
    logger.info(
        "site=%s minute=%s qualité=%s : %s",
        id_site,
        slot.isoformat(timespec="minutes"),
        reading.get("data_quality"),
        "insérée" if inserted else "déjà collectée",
    )
    return int(inserted)


def collect(now: datetime | None = None) -> dict[str, int]:
    """Collecte la mesure instantanée de tous les sites actifs déclarés.

    ``now`` sans fuseau est lu comme de l'UTC, comme les horodatages de
    l'API Mock.
    """
    now = to_utc(now or datetime.now(tz=UTC))

    with get_engine().connect() as conn:
        declared = load_declared_sites(conn)
    if not declared:
        logger.error(
            "aucun site actif dans app.site : rien à collecter "
            "(déclarer les sites, voir db/08_sites_demo.sql)"
        )
        sys.exit(EXIT_NO_DECLARED_SITE)

    # Appels en parallèle, contrôle /sites compris : un site ou un /sites lent
    # (timeout et retries) ne doit pas faire durer le passage plus d'une
    # minute, sinon supercronic saute le suivant. La session HTTP partagée
    # est sûre ici : seul son pool de connexions (urllib3, thread-safe) sert.
    with ThreadPoolExecutor(max_workers=len(declared) + 1) as pool:
        sites_check = pool.submit(_warn_on_inconsistent_sites, declared)
        futures = {s: pool.submit(get_current_reading, s) for s in declared}

    try:
        sites_check.result()
    except Exception:
        logger.exception("contrôle des sites : erreur inattendue")

    total_inserted = sites_in_error = 0
    for id_site, future in futures.items():
        try:
            total_inserted += collect_site(id_site, future.result(), now)
        except requests.RequestException as exc:
            logger.error("site %s : échec API — %s", id_site, exc)
            sites_in_error += 1
        except ReadingRejected as exc:
            logger.error("site %s : %s", id_site, exc)
            sites_in_error += 1
        except SQLAlchemyError as exc:
            logger.error("site %s : échec de l'insertion en bronze — %s", id_site, exc)
            sites_in_error += 1
        except Exception:
            # Une erreur imprévue sur un site n'arrête pas les autres
            logger.exception("site %s : erreur inattendue", id_site)
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
    configure_logging("etl")
    collect()
