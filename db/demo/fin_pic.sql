-- =============================================================================
-- EnerVision : fin du pic de la démo
--
-- Arrête le pic de db/demo/pic.sql et retire son trigger, sa fonction et sa
-- table : les mesures suivantes sont celles de l'API Mock, l'alerte se ferme
-- 3 minutes plus tard. À lancer à la fin du tournage.
--
-- Avec le compte admin PostgreSQL :
--   docker exec -i postgres \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/demo/fin_pic.sql
-- =============================================================================

BEGIN;

DROP TRIGGER IF EXISTS trg_demo_pic ON bronze.raw_readings;

DROP FUNCTION IF EXISTS bronze.demo_pic_appliquer();

DROP TABLE IF EXISTS bronze.demo_pic;

COMMIT;
