"""Script de vérification E2E du pipeline ETL EnerVision.

Vérifie en séquence :
  1. Connexion PostgreSQL + existence des schémas et tables
  2. Ping de l'API Mock (GET /api/v1/sites)
  3. Collecte Bronze (collect.run)
  4. Nettoyage Silver (clean.run)
  5. Agrégation Gold (aggregate.run)
  6. Contrôle des compteurs : bronze, silver, gold_latest, gold_hourly, alertes

Exécution (depuis la racine du projet) :
    python -m etl.check

Codes de sortie :
    0 — tous les checks passent
    1 — au moins un check a échoué
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from common.config import get_settings
from common.db import get_engine
from etl import aggregate, clean, collect
from etl.api_client import get_sites

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────

_PASS = "✅ PASS"
_FAIL = "❌ FAIL"
_WARN = "⚠️  WARN"

results: list[tuple[str, str, str]] = []   # (label, statut, détail)


def check(label: str, ok: bool, detail: str = "", warn: bool = False) -> bool:
    """Enregistre un résultat de vérification et l'affiche."""
    if ok:
        status = _PASS
    elif warn:
        status = _WARN
    else:
        status = _FAIL
    results.append((label, status, detail))
    logger.info("  %s  %s%s", status, label, f" — {detail}" if detail else "")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# 1. Connexion PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────

def check_db() -> bool:
    logger.info("\n── 1. PostgreSQL ─────────────────────────────────")
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        ok_conn = check("Connexion PostgreSQL", True)
    except Exception as exc:
        check("Connexion PostgreSQL", False, str(exc))
        logger.error("  Impossible de continuer sans la base — arrêt.")
        return False

    # Vérification des schémas
    try:
        with engine.connect() as conn:
            schemas = {
                r[0] for r in conn.execute(
                    text("SELECT schema_name FROM information_schema.schemata")
                )
            }
        for schema in ("bronze", "silver", "gold"):
            check(f"Schéma {schema}", schema in schemas)
    except Exception as exc:
        check("Schémas", False, str(exc))

    # Vérification des tables attendues
    expected_tables: dict[str, list[str]] = {
        "bronze": ["raw_readings"],
        "silver": ["silver_readings"],
        "gold":   ["gold_latest", "gold_hourly", "gold_alerts",
                   "etat_capteur", "recommandation"],
    }
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema IN ('bronze','silver','gold')
            """))
            existing = {(r[0], r[1]) for r in rows}
        for schema, tables in expected_tables.items():
            for table in tables:
                present = (schema, table) in existing
                check(f"Table {schema}.{table}", present)
    except Exception as exc:
        check("Tables", False, str(exc))

    # Vérification colonne payload JSONB sur bronze.raw_readings
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'bronze'
                  AND table_name   = 'raw_readings'
                  AND column_name  = 'payload'
            """)).fetchone()
        has_payload = row is not None and row[0] == "jsonb"
        check("bronze.raw_readings.payload (JSONB)", has_payload,
              "colonne introuvable ou mauvais type" if not has_payload else "")
    except Exception as exc:
        check("bronze.raw_readings.payload", False, str(exc))

    return True


# ─────────────────────────────────────────────────────────────────────────────
# 2. API Mock
# ─────────────────────────────────────────────────────────────────────────────

def check_api() -> bool:
    logger.info("\n── 2. API Mock ───────────────────────────────────")
    try:
        sites = get_sites()
        ok = len(sites) > 0
        check("GET /api/v1/sites", ok, f"{len(sites)} site(s) retournés")
        if ok:
            check("Sites contiennent capacity_kw", all("capacity_kw" in s for s in sites),
                  "capacity_kw absent d'un site" if not all("capacity_kw" in s for s in sites) else "")
        return ok
    except Exception as exc:
        check("GET /api/v1/sites", False, str(exc))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. collect.run() → Bronze
# ─────────────────────────────────────────────────────────────────────────────

def check_collect() -> dict[str, int]:
    logger.info("\n── 3. Collect → Bronze ───────────────────────────")
    try:
        t0 = time.monotonic()
        stats = collect.run()
        elapsed = time.monotonic() - t0

        inserted = stats.get("readings_inserted", 0)
        skipped  = stats.get("readings_skipped", 0)

        check("collect.run() s'exécute sans erreur", True, f"{elapsed:.2f}s")
        check("Au moins 1 mesure insérée ou déjà présente",
              inserted > 0 or skipped > 0,
              f"inserted={inserted} skipped={skipped}")

        # Compter le total en base
        with get_engine().connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM bronze.raw_readings")
            ).scalar()
        check("bronze.raw_readings non vide", (total or 0) > 0, f"{total} ligne(s)")

        # Vérifier qu'au moins une ligne a un payload avec _site
        with get_engine().connect() as conn:
            has_site = conn.execute(text("""
                SELECT COUNT(*) FROM bronze.raw_readings
                WHERE payload ? '_site'
            """)).scalar()
        check("payload contient _site", (has_site or 0) > 0,
              f"{has_site} ligne(s) avec _site dans le payload")

        return stats
    except Exception as exc:
        check("collect.run()", False, str(exc))
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 4. clean.run() → Silver
# ─────────────────────────────────────────────────────────────────────────────

def check_clean() -> dict[str, int]:
    logger.info("\n── 4. Clean → Silver ─────────────────────────────")
    try:
        t0 = time.monotonic()
        stats = clean.run()
        elapsed = time.monotonic() - t0

        processed = stats.get("processed", 0)
        check("clean.run() s'exécute sans erreur", True, f"{elapsed:.2f}s")

        with get_engine().connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM silver.silver_readings")
            ).scalar()
        check("silver.silver_readings non vide", (total or 0) > 0, f"{total} ligne(s)")

        # Vérifier que load_percent est calculé (capacity_kw lu depuis JSONB)
        with get_engine().connect() as conn:
            with_load = conn.execute(text("""
                SELECT COUNT(*) FROM silver.silver_readings
                WHERE load_percent IS NOT NULL
            """)).scalar()
        check("load_percent calculé depuis payload._site.capacity_kw",
              (with_load or 0) > 0,
              f"{with_load} ligne(s) avec load_percent non NULL")

        return stats
    except Exception as exc:
        check("clean.run()", False, str(exc))
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 5. aggregate.run() → Gold
# ─────────────────────────────────────────────────────────────────────────────

def check_aggregate() -> dict[str, Any]:
    logger.info("\n── 5. Aggregate → Gold ───────────────────────────")
    try:
        now = datetime.now(tz=timezone.utc)
        t0 = time.monotonic()
        stats = aggregate.run(now=now)
        elapsed = time.monotonic() - t0

        check("aggregate.run() s'exécute sans erreur", True, f"{elapsed:.2f}s")

        nb_latest = stats.get("gold_latest", 0)
        check("gold_latest mis à jour", nb_latest > 0, f"{nb_latest} site(s)")

        with get_engine().connect() as conn:
            total_alerts = conn.execute(
                text("SELECT COUNT(*) FROM gold.gold_alerts")
            ).scalar()
        check("gold.gold_alerts accessible", True, f"{total_alerts} alerte(s) au total")

        with get_engine().connect() as conn:
            total_capteurs = conn.execute(
                text("SELECT COUNT(*) FROM gold.etat_capteur")
            ).scalar()
        check("gold.etat_capteur mis à jour",
              (total_capteurs or 0) > 0,
              f"{total_capteurs} capteur(s)",
              warn=(total_capteurs or 0) == 0)

        return stats
    except Exception as exc:
        check("aggregate.run()", False, str(exc))
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Rapport final
# ─────────────────────────────────────────────────────────────────────────────

def print_report() -> int:
    """Affiche le récapitulatif et retourne le code de sortie (0 = OK, 1 = KO)."""
    passes = sum(1 for _, s, _ in results if s == _PASS)
    warns  = sum(1 for _, s, _ in results if s == _WARN)
    fails  = sum(1 for _, s, _ in results if s == _FAIL)
    total  = len(results)

    logger.info("\n%s", "═" * 55)
    logger.info("RÉSULTAT : %d/%d checks passés  |  %d warning(s)  |  %d échec(s)",
                passes, total, warns, fails)
    if fails:
        logger.info("\nChecks échoués :")
        for label, status, detail in results:
            if status == _FAIL:
                logger.info("  %s  %s — %s", status, label, detail)
    logger.info("═" * 55)

    return 0 if fails == 0 else 1


# ─────────────────────────────────────────────────────────────────────────────

def run() -> int:
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║   EnerVision — Vérification E2E Pipeline ETL         ║")
    logger.info("╚══════════════════════════════════════════════════════╝")

    db_ok = check_db()
    if not db_ok:
        return print_report()

    api_ok = check_api()
    if not api_ok:
        logger.warning("API Mock inaccessible — les checks collect/clean/aggregate seront skippés.")
        return print_report()

    check_collect()
    check_clean()
    check_aggregate()

    return print_report()


if __name__ == "__main__":
    sys.exit(run())
