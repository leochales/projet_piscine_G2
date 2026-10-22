-- =============================================================================
-- EnerVision : initialisation de l'entrepôt de données
-- 03 : tables de app
--
-- Exécuté une seule fois, au premier démarrage du conteneur PostgreSQL
-- =============================================================================

BEGIN;

-- Entreprises clientes d'EnerVision
CREATE TABLE IF NOT EXISTS app.client (
    id_client BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nom VARCHAR(100) NOT NULL UNIQUE,
    date_creation TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Les comptes, rôles et mots de passe sont gérés par Keycloak.
-- On garde l'identifiant Keycloak et le client.
-- id_client NULL : compte interne EnerVision (administrateur), sans client.
CREATE TABLE IF NOT EXISTS app.utilisateur (
    id UUID PRIMARY KEY,
    id_client BIGINT REFERENCES app.client (id_client),
    date_creation TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_utilisateur_client ON app.utilisateur (
    id_client
);

-- Référentiel des sites, géré par l'application : un site est déclaré
-- et rattaché à un client avant d'être collecté. L'ETL ignore les sites
-- de l'API Mock qui ne sont pas déclarés ici.
CREATE TABLE IF NOT EXISTS app.site (
    id_site VARCHAR(20) PRIMARY KEY,           -- identifiant de l'API Mock
    id_client BIGINT NOT NULL REFERENCES app.client (id_client),
    nom VARCHAR(100) NOT NULL,
    type VARCHAR(30) NOT NULL,  -- noqa: RF04
    localisation VARCHAR(100),
    capacite_kw NUMERIC(10, 2) NOT NULL CHECK (capacite_kw > 0),
    statut VARCHAR(20) NOT NULL DEFAULT 'active',
    date_creation TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_site_client ON app.site (id_client);

COMMIT;
