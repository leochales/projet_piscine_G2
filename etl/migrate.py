"""Migration de schéma Bronze + Gold — EnerVision.

Applique les modifications DDL (ALTER TABLE + CREATE TABLE) sur les couches
Bronze et Gold pour les déploiements existants. Idempotent : peut être rejoué
sans erreur.

Les fichiers db/01_bronze.sql et db/03_gold.sql contiennent le schéma complet
pour les installations fraîches. Ce script sert uniquement à mettre à jour des
bases déjà initialisées.

Migration Bronze v2 (JSONB unique) :
  - Supprime bronze.dim_sites (plus nécessaire : infos site dénormalisées dans payload)
  - Supprime les colonnes structurées de bronze.raw_readings
  - Ajoute la colonne payload JSONB

Exécution :
    python -m etl.migrate
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from common.db import get_engine

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Instructions DDL — toutes idempotentes
# ─────────────────────────────────────────────────────────────────────────────

_SQL_BRONZE: list[str] = [
    # ── Ajout de la colonne payload JSONB ────────────────────────────────────
    """
    ALTER TABLE bronze.raw_readings
        ADD COLUMN IF NOT EXISTS payload JSONB
    """,
    # ── Index GIN sur payload ─────────────────────────────────────────────────
    """
    CREATE INDEX IF NOT EXISTS idx_raw_readings_payload
        ON bronze.raw_readings USING GIN (payload)
    """,
    # ── Suppression des colonnes structurées redondantes ─────────────────────
    # (idempotent via IF EXISTS — safe sur une base fraîche sans ces colonnes)
    """
    ALTER TABLE bronze.raw_readings
        DROP COLUMN IF EXISTS site_type,
        DROP COLUMN IF EXISTS consumption_kw,
        DROP COLUMN IF EXISTS consumption_kwh,
        DROP COLUMN IF EXISTS voltage_v,
        DROP COLUMN IF EXISTS current_a,
        DROP COLUMN IF EXISTS power_factor,
        DROP COLUMN IF EXISTS temperature_celsius,
        DROP COLUMN IF EXISTS humidity_percent,
        DROP COLUMN IF EXISTS null_reasons,
        DROP COLUMN IF EXISTS raw_payload
    """,
    # ── Suppression de la table dim_sites (plus utilisée) ────────────────────
    # ATTENTION : cette instruction supprime la table et toutes ses données.
    # Idempotent via IF EXISTS.
    """
    DROP TABLE IF EXISTS bronze.dim_sites
    """,
    # ── Mise à jour des permissions ───────────────────────────────────────────
    "GRANT SELECT, INSERT ON bronze.raw_readings TO enervision_worker",
    "GRANT USAGE, SELECT ON SEQUENCE bronze.raw_readings_id_seq TO enervision_worker",
]

_SQL_GOLD: list[str] = [
    # ── gold_latest : colonnes supplémentaires ────────────────────────────────
    """
    ALTER TABLE gold.gold_latest
        ADD COLUMN IF NOT EXISTS facteur_puissance FLOAT8,
        ADD COLUMN IF NOT EXISTS null_reasons      TEXT[]
    """,

    # ── gold_hourly : consommation kWh + coût EUR ────────────────────────────
    """
    ALTER TABLE gold.gold_hourly
        ADD COLUMN IF NOT EXISTS consommation_kwh FLOAT4,
        ADD COLUMN IF NOT EXISTS cout_eur         FLOAT4
    """,

    # ── gold_alerts : source + période debut/fin ──────────────────────────────
    """
    ALTER TABLE gold.gold_alerts
        ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'silver',
        ADD COLUMN IF NOT EXISTS debut  TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS fin    TIMESTAMPTZ
    """,
    # Contrainte CHECK sur source (ignorée si déjà présente)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'chk_alerts_source'
              AND conrelid = 'gold.gold_alerts'::regclass
        ) THEN
            ALTER TABLE gold.gold_alerts
                ADD CONSTRAINT chk_alerts_source CHECK (source IN ('silver', 'api'));
        END IF;
    END $$
    """,

    # ── gold_predictions : colonnes ML supplémentaires ────────────────────────
    """
    ALTER TABLE gold.gold_predictions
        ADD COLUMN IF NOT EXISTS consommation_prevue_kwh FLOAT4,
        ADD COLUMN IF NOT EXISTS pic_prevu               BOOLEAN
    """,

    # ── Nouvelle table : gold.etat_capteur ────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS gold.etat_capteur (
        capteur          VARCHAR(50)  NOT NULL,
        site_id          VARCHAR(10)  NOT NULL,
        statut           VARCHAR(20)  NOT NULL DEFAULT 'ok',
        en_panne_jusqu_a TIMESTAMPTZ,
        mis_a_jour_le    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

        CONSTRAINT pk_etat_capteur    PRIMARY KEY (capteur, site_id),
        CONSTRAINT chk_capteur_statut CHECK (statut IN ('ok', 'en_panne', 'degrade'))
    )
    """,

    # ── Nouvelle table : gold.performance_modele ──────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS gold.performance_modele (
        id             BIGSERIAL    NOT NULL,
        version_modele VARCHAR(50)  NOT NULL,
        evalue_le      TIMESTAMPTZ  NOT NULL,
        mae            FLOAT4,
        rmse           FLOAT4,
        score_drift    FLOAT4,

        CONSTRAINT pk_perf_modele PRIMARY KEY (id),
        CONSTRAINT uq_perf_modele UNIQUE (version_modele, evalue_le)
    )
    """,

    # ── Nouvelle table : gold.recommandation ──────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS gold.recommandation (
        id            BIGSERIAL    NOT NULL,
        alert_id      VARCHAR(60)  NOT NULL,
        regle         VARCHAR(50)  NOT NULL,
        titre         VARCHAR(200) NOT NULL,
        description   TEXT,
        date_creation TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

        CONSTRAINT pk_recommandation PRIMARY KEY (id)
    )
    """,

    # ── Index sur les nouvelles tables ────────────────────────────────────────
    "CREATE INDEX IF NOT EXISTS idx_etat_capteur_site    ON gold.etat_capteur      (site_id)",
    "CREATE INDEX IF NOT EXISTS idx_perf_modele_version  ON gold.performance_modele (version_modele, evalue_le DESC)",
    "CREATE INDEX IF NOT EXISTS idx_recommandation_alert ON gold.recommandation     (alert_id)",

    # ── Permissions sur les nouvelles tables ──────────────────────────────────
    "GRANT SELECT, INSERT, UPDATE ON gold.etat_capteur      TO enervision_worker",
    "GRANT SELECT, INSERT         ON gold.performance_modele TO enervision_worker",
    "GRANT SELECT, INSERT         ON gold.recommandation     TO enervision_worker",

    "GRANT SELECT ON gold.etat_capteur      TO enervision_api",
    "GRANT SELECT ON gold.performance_modele TO enervision_api",
    "GRANT SELECT ON gold.recommandation     TO enervision_api",

    "GRANT USAGE, SELECT ON SEQUENCE gold.performance_modele_id_seq TO enervision_worker",
    "GRANT USAGE, SELECT ON SEQUENCE gold.recommandation_id_seq     TO enervision_worker",
]


def _run_batch(conn, batch: list[str], label: str) -> None:
    """Exécute une liste d'instructions DDL idempotentes dans la connexion ouverte."""
    for i, sql in enumerate(batch, start=1):
        stmt = sql.strip()
        if not stmt:
            continue
        first_line = stmt.split("\n")[0][:70].strip()
        logger.info("[MIGRATE] %s %d/%d — %s …", label, i, len(batch), first_line)
        conn.execute(text(stmt))


def run() -> None:
    """Applique toutes les migrations Bronze + Gold de façon idempotente."""
    engine = get_engine()
    with engine.begin() as conn:
        _run_batch(conn, _SQL_BRONZE, "Bronze")
        _run_batch(conn, _SQL_GOLD,   "Gold")

    logger.info(
        "[MIGRATE] Migration terminée — %d instruction(s) Bronze, %d Gold.",
        len(_SQL_BRONZE), len(_SQL_GOLD),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
