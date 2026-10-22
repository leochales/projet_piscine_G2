-- =============================================================================
-- EnerVision : initialisation de l'entrepôt de données
-- 02 : tables de bronze
--
-- Exécuté une seule fois, au premier démarrage du conteneur PostgreSQL
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS bronze.raw_readings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_site VARCHAR(20) NOT NULL,
    horodatage TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL,
    UNIQUE (id_site, horodatage)
);

COMMIT;
