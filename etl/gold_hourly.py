"""ETL — Consommation horaire dans gold (silver → gold.consommation_horaire).

Le calcul est fait par la fonction SQL ``gold.calculer_consommation_horaire()``
(db/12_gold_horaire.sql), testée en CI par db/tests/test_gold_horaire.sql :
  - consommation_kwh = Σ kW × 1/60 h sur les minutes qui ont une consommation
    (mesurée ou imputée) ;
  - pic_kw, moyenne_kw, nb_mesures, nb_imputees ;
  - taux_couverture = nb_mesures / 60 (sous 1, les kWh sont sous-estimés) ;
  - heure_complete : silver contient les 60 minutes de l'heure.

Chaque exécution recalcule, par site, la dernière heure déjà en gold et la
précédente, puis les heures suivantes : l'heure en cours est à jour chaque
minute, et une imputation tardive corrige l'heure précédente.

Le coût en € n'est pas stocké : l'API le calcule à partir des kWh
(api/routers/mesures.py), pour qu'un changement de tarif ne demande pas de
recalculer gold.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text

from common.db import get_engine
from common.logs import configure_logging

logger = logging.getLogger(__name__)


def upsert_hourly(conn: Connection) -> dict[str, int]:
    """Recalcule les heures à mettre à jour. Retourne le nombre d'heures par site."""
    sql = text("SELECT id_site, heures FROM gold.calculer_consommation_horaire()")
    return {r.id_site: r.heures for r in conn.execute(sql)}


def aggregate() -> dict[str, int]:
    """Met à jour gold.consommation_horaire pour tous les sites actifs."""
    with get_engine().begin() as conn:
        hours = upsert_hourly(conn)
    for id_site, n in sorted(hours.items()):
        logger.info("site=%s : %d heure(s) recalculée(s)", id_site, n)
    return {"sites": len(hours), "hours_written": sum(hours.values())}


if __name__ == "__main__":
    configure_logging("etl")
    aggregate()
