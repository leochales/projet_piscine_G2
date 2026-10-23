-- =============================================================================
-- EnerVision : migration 001
-- Silver représente les minutes sans mesure, et une quarantaine accueille
-- les mesures refusées par la validation.
--
-- À exécuter une fois sur une base créée avant ce changement (les scripts
-- de db/ ne tournent qu'au premier démarrage). Rejouable sans effet.
--   docker exec -i postgres \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
--     < db/migrations/001_silver_grille.sql
-- =============================================================================

BEGIN;

ALTER TABLE silver.silver_readings ALTER COLUMN bronze_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS silver.rejected_readings (
    bronze_id BIGINT PRIMARY KEY REFERENCES bronze.raw_readings (id),
    id_site VARCHAR(20) NOT NULL,
    horodatage TIMESTAMPTZ NOT NULL,
    errors JSONB NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Créée après 06_roles.sql : les privilèges par défaut ne s'appliquent que
-- si le propriétaire est le même compte, on accorde donc explicitement
GRANT SELECT, INSERT, UPDATE, DELETE ON silver.rejected_readings TO etl;
GRANT SELECT ON silver.rejected_readings TO model;

COMMIT;
