-- ============================================================
-- EnerVision — Schéma BRONZE
-- Script : 01_bronze.sql
-- Données brutes copiées telles quelles depuis l'API Mock.
-- Règle d'or : on n'écrase jamais une ligne une fois insérée.
--
-- Architecture : 1 seule table JSONB.
--   payload = merge du dict site + dict reading retourné par l'API Mock.
--   Les infos du site (capacity_kw, site_type, …) sont dénormalisées
--   dans le payload au moment de la collecte — pas besoin de dim_sites.
-- ============================================================

SET search_path TO bronze;

-- ── Mesures IoT brutes ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS bronze.raw_readings (
    id           BIGSERIAL    NOT NULL,
    site_id      VARCHAR(10)  NOT NULL,         -- dupliqué pour indexation/dédup rapide
    timestamp    TIMESTAMPTZ  NOT NULL,         -- dupliqué pour la contrainte UNIQUE
    data_quality VARCHAR(10)  NOT NULL DEFAULT 'good',  -- good | partial | degraded | critical
    ingested_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),   -- timestamp d'insertion ETL

    payload      JSONB        NOT NULL,         -- merge complet site + reading (voir collect.py)

    CONSTRAINT pk_raw_readings  PRIMARY KEY (id),
    CONSTRAINT chk_raw_quality  CHECK (data_quality IN ('good','partial','degraded','critical')),
    CONSTRAINT uq_raw_site_ts   UNIQUE (site_id, timestamp)  -- dédup si collect.py rejoue
);

COMMENT ON TABLE  bronze.raw_readings IS 'Mesures IoT brutes — 1 seule table JSONB. payload = merge site+reading de l''API Mock. Collecte toutes les minutes.';
COMMENT ON COLUMN bronze.raw_readings.payload      IS 'Merge du dict site (capacity_kw, site_name, site_type, …) et du dict reading. Permet de rejouer Silver sans perte et sans rejoindre une table de référentiel.';
COMMENT ON COLUMN bronze.raw_readings.data_quality IS 'Déduit par collect.py depuis null_reasons : good | partial | degraded | critical.';
COMMENT ON COLUMN bronze.raw_readings.ingested_at  IS 'Timestamp d''insertion dans PostgreSQL — différent du timestamp de mesure.';

-- ── Index ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_raw_readings_site_id   ON bronze.raw_readings (site_id);
CREATE INDEX IF NOT EXISTS idx_raw_readings_timestamp ON bronze.raw_readings (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_raw_readings_quality   ON bronze.raw_readings (data_quality);
-- Composite pour clean.py (lignes non encore dans Silver, par site + timestamp)
CREATE INDEX IF NOT EXISTS idx_raw_readings_site_ts   ON bronze.raw_readings (site_id, timestamp DESC);
-- GIN pour requêtes sur le payload (ex : WHERE payload @> '{"site_type":"office"}')
CREATE INDEX IF NOT EXISTS idx_raw_readings_payload   ON bronze.raw_readings USING GIN (payload);

-- ── Permissions ────────────────────────────────────────────
GRANT SELECT, INSERT ON bronze.raw_readings TO enervision_worker;
GRANT USAGE, SELECT ON SEQUENCE bronze.raw_readings_id_seq TO enervision_worker;
