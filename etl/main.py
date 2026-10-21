"""Orchestrateur ETL EnerVision.

Exécution : python -m etl.main
Planning  : etl/crontab (supercronic)

Ordre d'exécution :
  1. collect.py  → bronze (données brutes API Mock)
  2. clean.py    → silver (imputation + features ML)
  3. aggregate.py → gold  (agrégats + alertes)
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

from common.config import get_settings
from etl import aggregate, clean, collect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def run() -> None:
    if not get_settings().etl_enabled:
        logger.info("ETL_ENABLED=false — pipeline désactivé, sortie.")
        return

    now   = datetime.now(tz=timezone.utc)
    start = time.monotonic()

    logger.info("=" * 60)
    logger.info("ETL EnerVision — %s", now.isoformat(timespec="seconds"))
    logger.info("=" * 60)

    # ── Bronze ─────────────────────────────────────────────────
    try:
        stats_collect = collect.run()
        logger.info("COLLECT → %s", stats_collect)
    except Exception:
        logger.exception("COLLECT échoué — poursuite du pipeline")
        stats_collect = {}

    # ── Silver ─────────────────────────────────────────────────
    try:
        stats_clean = clean.run()
        logger.info("CLEAN   → %s", stats_clean)
    except Exception:
        logger.exception("CLEAN échoué — poursuite du pipeline")
        stats_clean = {}

    # ── Gold ───────────────────────────────────────────────────
    try:
        stats_agg = aggregate.run(now=now)
        logger.info("AGG     → %s", stats_agg)
    except Exception:
        logger.exception("AGGREGATE échoué")
        stats_agg = {}

    elapsed = time.monotonic() - start
    logger.info("Pipeline terminé en %.2fs", elapsed)


if __name__ == "__main__":
    run()
