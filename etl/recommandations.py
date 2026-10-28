"""ETL — Recommandations dans gold (gold.alerte → gold.recommandation).

Les recommandations viennent de règles simples, pas du modèle : chaque alerte
en cours (API Mock, pics de l'ETL, pics prévus par le modèle) reçoit la
recommandation de la règle qui correspond à son type et à sa sévérité.

Les règles et le calcul sont en base (db/18_gold_recommandations.sql), testés
en CI par db/tests/test_gold_recommandations.sql :
  - table gold.regle_recommandation : règle exacte, sinon règle du type,
    sinon règle générique ;
  - fonction gold.generer_recommandations(prix) : une recommandation par
    alerte en cours, avec un gain estimé pour les dépassements de seuil ;
    tant que personne n'a décidé, elle suit la sévérité et la valeur de
    l'alerte.

Le prix du kWh vient de PRIX_KWH_EUR (common/config.py), comme pour l'API.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from common.config import get_settings
from common.db import get_engine
from common.logs import configure_logging

logger = logging.getLogger(__name__)


def generate() -> dict[str, int]:
    """Crée et met à jour les recommandations des alertes en cours."""
    sql = text("SELECT creees, mises_a_jour FROM gold.generer_recommandations(:prix)")
    with get_engine().begin() as conn:
        row = conn.execute(sql, {"prix": get_settings().prix_kwh_eur}).one()
    logger.info(
        "%d recommandation(s) créée(s), %d mise(s) à jour", row.creees, row.mises_a_jour
    )
    return {"creees": row.creees, "mises_a_jour": row.mises_a_jour}


if __name__ == "__main__":
    configure_logging("etl")
    generate()
