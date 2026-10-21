-- ============================================================
-- EnerVision — Initialisation des schémas PostgreSQL
-- Script : 00_init_schemas.sql
-- À exécuter en premier, avec le rôle superuser (postgres)
-- ============================================================

-- Schémas de la Medallion Architecture
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- ── Rôles applicatifs (optionnel mais recommandé) ──────────
-- worker : lit Bronze/Silver, écrit partout
-- api     : lit uniquement Silver et Gold (lecture seule)

CREATE ROLE enervision_worker NOLOGIN;
CREATE ROLE enervision_api    NOLOGIN;

-- Accès aux schémas
GRANT USAGE ON SCHEMA bronze TO enervision_worker;
GRANT USAGE ON SCHEMA silver TO enervision_worker;
GRANT USAGE ON SCHEMA gold   TO enervision_worker;

GRANT USAGE ON SCHEMA silver TO enervision_api;
GRANT USAGE ON SCHEMA gold   TO enervision_api;

-- Les GRANT sur les tables sont faits dans chaque script DDL.
