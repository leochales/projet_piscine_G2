-- =============================================================================
-- EnerVision : initialisation de l'entrepôt de données
-- 01 : schémas
--
-- Exécuté une seule fois, au premier démarrage du conteneur PostgreSQL
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Schémas
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS bronze;   -- réponses brutes de l'API Mock (JSONB)
CREATE SCHEMA IF NOT EXISTS silver;   -- mesures nettoyées, typées et imputées
-- données prêtes à afficher par le dashboard
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS app;      -- données propres à l'application

-- Personne ne crée d'objet dans le schéma public
REVOKE ALL ON SCHEMA public FROM public;

COMMIT;
