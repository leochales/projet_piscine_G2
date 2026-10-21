-- ============================================================
-- EnerVision — Schéma SILVER
-- Script : 02_silver.sql
-- Données nettoyées et enrichies. Produit par clean.py.
-- Règles :
--   - consumption_kw_raw = copie exacte du bronze (jamais modifiée)
--   - consumption_kw_imputed = valeur après imputation
--   - load_percent = variable cible du modèle ML
-- ============================================================

SET search_path TO silver;

CREATE TABLE IF NOT EXISTS silver.silver_readings (
    id                      BIGSERIAL    NOT NULL,
    bronze_id               BIGINT       NOT NULL,   -- FK → bronze.raw_readings.id (traçabilité)
    timestamp               TIMESTAMPTZ  NOT NULL,
    site_id                 VARCHAR(10)  NOT NULL,

    -- ── Consommation ───────────────────────────────────────
    consumption_kw_raw      FLOAT8,                  -- valeur brute copiée depuis Bronze (peut être NULL)
    consumption_kw_imputed  FLOAT8,                  -- valeur après imputation (jamais NULL si imputation OK)
    is_imputed              BOOLEAN      NOT NULL DEFAULT FALSE,
    imputation_method       VARCHAR(25)  NOT NULL DEFAULT 'none',
    -- none | linear_interpolation | forward_fill | rolling_mean

    -- ── Autres mesures (copiées depuis Bronze) ─────────────
    consumption_kwh         FLOAT8,
    voltage_v               FLOAT8,
    current_a               FLOAT8,
    power_factor            FLOAT8,
    temperature_celsius     FLOAT8,
    humidity_percent        FLOAT8,

    -- ── Qualité ────────────────────────────────────────────
    data_quality            VARCHAR(10)  NOT NULL,
    quality_score           FLOAT4       NOT NULL,
    -- 1.0 = good | 0.7 = partial | 0.4 = degraded | 0.0 = critical

    -- ── Features ML (calculées par clean.py) ───────────────
    hour_of_day             SMALLINT,    -- 0–23
    day_of_week             SMALLINT,    -- 0=lundi … 6=dimanche
    is_weekend              BOOLEAN,
    month                   SMALLINT,    -- 1–12

    -- Variable cible : taux de charge normalisé (invariant inter-sites)
    load_percent            FLOAT4,      -- consumption_kw_imputed / capacity_kw * 100

    -- Lags temporels (NULL sur les premières lignes de chaque site)
    load_lag_1h             FLOAT4,      -- load_percent il y a 1h
    load_lag_24h            FLOAT4,      -- load_percent il y a 24h
    load_rolling_3h         FLOAT4,      -- moyenne glissante sur 3h

    processed_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_silver_readings   PRIMARY KEY (id),
    CONSTRAINT fk_silver_bronze     FOREIGN KEY (bronze_id)
                                    REFERENCES bronze.raw_readings (id)
                                    ON DELETE RESTRICT,
    CONSTRAINT uq_silver_site_ts    UNIQUE (site_id, timestamp),
    CONSTRAINT chk_silver_quality   CHECK (data_quality IN ('good','partial','degraded','critical')),
    CONSTRAINT chk_silver_qscore    CHECK (quality_score BETWEEN 0.0 AND 1.0),
    CONSTRAINT chk_silver_method    CHECK (imputation_method IN ('none','linear_interpolation','forward_fill','rolling_mean')),
    CONSTRAINT chk_silver_hour      CHECK (hour_of_day   BETWEEN 0 AND 23),
    CONSTRAINT chk_silver_dow       CHECK (day_of_week   BETWEEN 0 AND 6),
    CONSTRAINT chk_silver_month     CHECK (month         BETWEEN 1 AND 12),
    CONSTRAINT chk_silver_load      CHECK (load_percent  BETWEEN 0.0 AND 150.0)
    -- 150% = marge pour les pics anormaux sans rejeter les données
);

COMMENT ON TABLE  silver.silver_readings IS 'Mesures nettoyées, imputées et enrichies de features ML. Table d''entraînement du modèle.';
COMMENT ON COLUMN silver.silver_readings.bronze_id             IS 'Lien de traçabilité vers la ligne brute d''origine.';
COMMENT ON COLUMN silver.silver_readings.consumption_kw_raw    IS 'Copie exacte de bronze — jamais modifiée, même si NULL.';
COMMENT ON COLUMN silver.silver_readings.consumption_kw_imputed IS 'Valeur utilisée pour les calculs. = raw si non-NULL, sinon valeur reconstituée.';
COMMENT ON COLUMN silver.silver_readings.load_percent          IS 'VARIABLE CIBLE ML. consumption_kw_imputed / capacity_kw * 100. Normalisée 0–100+ pour être invariante inter-sites.';
COMMENT ON COLUMN silver.silver_readings.load_lag_1h           IS 'Feature ML : valeur de load_percent 1h avant pour ce site.';
COMMENT ON COLUMN silver.silver_readings.load_lag_24h          IS 'Feature ML : valeur de load_percent 24h avant (pattern journalier).';
COMMENT ON COLUMN silver.silver_readings.load_rolling_3h       IS 'Feature ML : moyenne glissante de load_percent sur les 3 dernières heures.';

-- ── Index ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_silver_site_id   ON silver.silver_readings (site_id);
CREATE INDEX IF NOT EXISTS idx_silver_timestamp ON silver.silver_readings (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_silver_site_ts   ON silver.silver_readings (site_id, timestamp DESC);
-- Index pour les requêtes ML (récupère les N dernières lignes par site pour construire les lags)
CREATE INDEX IF NOT EXISTS idx_silver_site_ts_load ON silver.silver_readings (site_id, timestamp DESC)
    INCLUDE (load_percent);

-- ── Permissions ────────────────────────────────────────────
GRANT SELECT, INSERT ON silver.silver_readings TO enervision_worker;
GRANT SELECT          ON silver.silver_readings TO enervision_api;
GRANT USAGE, SELECT ON SEQUENCE silver.silver_readings_id_seq TO enervision_worker;
