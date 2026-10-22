-- =============================================================================
-- EnerVision : initialisation de l'entrepôt de données
-- 04 : tables de silver
--
-- Exécuté une seule fois, au premier démarrage du conteneur PostgreSQL
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS silver.silver_readings (
    id_site VARCHAR(20) NOT NULL REFERENCES app.site (id_site),
    horodatage TIMESTAMPTZ NOT NULL,
    bronze_id BIGINT NOT NULL REFERENCES bronze.raw_readings (id),
    consumption_kw_raw NUMERIC(10, 2),
    consumption_kw_imputed NUMERIC(10, 2),
    imputation_method VARCHAR(25) NOT NULL DEFAULT 'none'
    CHECK (
        imputation_method IN (
            'none', 'linear_interpolation', 'forward_fill', 'rolling_mean'
        )
    ),
    voltage_v NUMERIC(6, 1),
    current_a NUMERIC(8, 2),
    power_factor NUMERIC(4, 3) CHECK (power_factor BETWEEN 0 AND 1),
    temperature_celsius NUMERIC(5, 2),
    humidity_percent NUMERIC(5, 2) CHECK (humidity_percent BETWEEN 0 AND 100),
    load_percent NUMERIC(6, 2) CHECK (load_percent >= 0),
    data_quality VARCHAR(10) NOT NULL
    CHECK (data_quality IN ('good', 'partial', 'degraded', 'critical')),
    null_reasons TEXT[] NOT NULL DEFAULT '{}',
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id_site, horodatage)
);

COMMIT;
