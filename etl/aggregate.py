"""ETL — Couche Gold : génération des recommandations liées aux alertes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text

from common.db import get_engine

logger = logging.getLogger(__name__)

# Règles de recommandation : (type, severite) → (regle, titre, description)
_REGLES_RECOMMANDATION: dict[tuple[str, str], tuple[str, str, str]] = {
    ("threshold", "high"): (
        "threshold_high",
        "Réduire la charge",
        (
            "La consommation dépasse 90 % de la capacité. Vérifier les équipements "
            "non essentiels et envisager un délestage partiel."
        ),
    ),
    ("threshold", "critical"): (
        "threshold_critical",
        "Délestage d'urgence requis",
        (
            "Surcharge détectée (> 110 %). Interrompre immédiatement les équipements "
            "non critiques pour éviter un déclenchement disjoncteur."
        ),
    ),
    ("spike", "high"): (
        "spike_detected",
        "Analyser le pic de consommation",
        (
            "Un pic anormal a été détecté. Identifier l'équipement déclencheur et "
            "vérifier son état de fonctionnement."
        ),
    ),
    ("spike", "critical"): (
        "spike_critical",
        "Pic critique — intervention immédiate",
        (
            "Pic de consommation critique. Couper les charges non essentielles et "
            "alerter le responsable de site."
        ),
    ),
    ("anomaly", "low"): (
        "anomaly_low",
        "Surveiller l'anomalie",
        (
            "Une anomalie de faible sévérité a été détectée. Aucune action immédiate "
            "requise, surveiller l'évolution sur les prochaines heures."
        ),
    ),
    ("anomaly", "medium"): (
        "anomaly_medium",
        "Diagnostic recommandé",
        (
            "Anomalie de consommation détectée. Lancer un diagnostic des capteurs et "
            "vérifier la cohérence des mesures."
        ),
    ),
    ("outage", "high"): (
        "outage_detected",
        "Coupure détectée — intervention maintenance",
        (
            "Une coupure d'alimentation a été enregistrée. Contacter la maintenance "
            "et vérifier les protections électriques."
        ),
    ),
    ("sensor", "medium"): (
        "sensor_issue",
        "Vérification capteur",
        (
            "Des données capteur manquantes ou incohérentes ont été détectées. "
            "Vérifier la connectivité et l'alimentation du capteur."
        ),
    ),
}


def _insert_recommandations_for_new_alerts() -> int:
    """Génère une recommandation par alerte en cours sans recommandation."""
    sql_select = text("""
        SELECT a.id_alerte, a.id_site, a.type, a.severite
        FROM gold.alerte a
        WHERE a.fin IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM gold.recommandation r WHERE r.id_alerte = a.id_alerte
          )
        ORDER BY a.debut DESC
        LIMIT 100
    """)
    sql_insert = text("""
        INSERT INTO gold.recommandation (
            id_site, id_alerte, regle, titre, description
        ) VALUES (
            :id_site, :id_alerte, :regle, :titre, :description
        )
    """)

    rows = []
    with get_engine().begin() as conn:
        for row in conn.execute(sql_select).fetchall():
            key = (row.type, row.severite)
            regle_info = _REGLES_RECOMMANDATION.get(key) or next(
                (v for (t, _), v in _REGLES_RECOMMANDATION.items() if t == row.type),
                (
                    "alerte_generique",
                    "Vérification requise",
                    (
                        "Une alerte a été déclenchée sur ce site. "
                        "Examiner les mesures récentes."
                    ),
                ),
            )
            rows.append(
                {
                    "id_site": row.id_site,
                    "id_alerte": row.id_alerte,
                    "regle": regle_info[0],
                    "titre": regle_info[1],
                    "description": regle_info[2],
                }
            )
        if rows:
            conn.execute(sql_insert, rows)
    return len(rows)


def run(now: datetime | None = None) -> dict[str, int]:
    """Point d'entrée : génère les recommandations manquantes."""
    if now is None:
        now = datetime.now(tz=UTC)
    logger.info("[AGGREGATE] Démarrage (%s)", now.strftime("%H:%M UTC"))
    nb = _insert_recommandations_for_new_alerts()
    logger.info("[AGGREGATE] recommandations=%d", nb)
    return {"recommandations": nb}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run()
