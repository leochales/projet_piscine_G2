-- =============================================================================
-- EnerVision : comptes des services et droits d'accès
-- Les comptes sont créés SANS mot de passe : ils sont définis par
-- 03_passwords.sh à partir des variables d'environnement (secrets GitHub).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Comptes des services
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['etl', 'model', 'api', 'backup'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r);
        END IF;
    END LOOP;
END
$$;

-- Seuls les comptes des services peuvent se connecter à la base
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO etl, model, api, backup', current_database());
END
$$;


-- -----------------------------------------------------------------------------
-- ETL : lecture et écriture sur bronze et silver, écriture sur gold,
--       lecture de 3 colonnes de app.site
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA bronze, silver, gold TO etl;

-- bronze : on ajoute des réponses brutes, on ne les modifie jamais
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA bronze TO etl;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA silver TO etl;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA bronze, silver TO etl;

ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT SELECT, INSERT ON TABLES TO etl;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO etl;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze, silver
GRANT USAGE ON SEQUENCES TO etl;

-- gold : « écriture » comprend SELECT et UPDATE, nécessaires aux mises à jour
-- (INSERT ... ON CONFLICT DO UPDATE, fermeture des alertes)
GRANT SELECT, INSERT, UPDATE
ON gold.derniere_mesure, gold.consommation_horaire, gold.etat_capteur,
gold.alerte, gold.recommandation
TO etl;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA gold TO etl;

-- app : lecture de 3 colonnes de app.site uniquement (quels sites collecter,
-- capacité pour détecter les dépassements). Ni clients ni utilisateurs.
GRANT USAGE ON SCHEMA app TO etl;
GRANT SELECT (id_site, capacite_kw, statut) ON app.site TO etl;


-- -----------------------------------------------------------------------------
-- Modèle : lecture de silver, écriture des prédictions dans gold,
--          lecture de 3 colonnes de app.site
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA silver, gold TO model;

GRANT SELECT ON ALL TABLES IN SCHEMA silver TO model;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT SELECT ON TABLES TO model;

-- SELECT sur prediction : relire les anciennes prédictions pour mesurer
-- le drift
GRANT SELECT, INSERT ON gold.prediction, gold.performance_modele TO model;
-- alertes « predicted_peak » produites par le modèle
GRANT SELECT, INSERT, UPDATE ON gold.alerte TO model;
GRANT USAGE ON SCHEMA app TO model;
GRANT SELECT (id_site, capacite_kw, statut) ON app.site TO model;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA gold TO model;


-- -----------------------------------------------------------------------------
-- API : lecture de gold, lecture et écriture de app
-- Aucun droit sur bronze ni silver
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA gold, app TO api;

GRANT SELECT ON ALL TABLES IN SCHEMA gold TO api;   -- tables et vues
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO api;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO api;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO api;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE ON SEQUENCES TO api;


-- -----------------------------------------------------------------------------
-- Sauvegarde : lecture seule sur tous les schémas (pg_dump)
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA bronze, silver, gold, app TO backup;

GRANT SELECT ON ALL TABLES IN SCHEMA bronze, silver, gold, app TO backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA bronze, silver, gold, app TO backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze, silver, gold, app
GRANT SELECT ON TABLES TO backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze, silver, gold, app
GRANT SELECT ON SEQUENCES TO backup;

COMMIT;
