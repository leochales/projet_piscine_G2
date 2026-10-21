-- =============================================================================
-- EnerVision : initialisation de l'entrepôt de données
-- 01 : schémas, tables de gold et de app
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


-- =============================================================================
-- APP
-- =============================================================================

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


-- =============================================================================
-- GOLD
-- =============================================================================

-- Une ligne par site, remplacée à chaque collecte
CREATE TABLE IF NOT EXISTS gold.derniere_mesure (
    id_site VARCHAR(20) PRIMARY KEY REFERENCES app.site (id_site),
    horodatage TIMESTAMPTZ NOT NULL,
    consommation_kw NUMERIC(10, 2),                -- NULL si la mesure manque
    facteur_puissance NUMERIC(4, 3) CHECK (facteur_puissance BETWEEN 0 AND 1),
    temperature_c NUMERIC(5, 2),
    data_quality VARCHAR(10) NOT NULL
    CHECK (data_quality IN ('good', 'partial', 'degraded', 'critical')),
    null_reasons TEXT[] NOT NULL DEFAULT '{}'
);

-- Agrégats horaires calculés par l'ETL à partir de silver
CREATE TABLE IF NOT EXISTS gold.consommation_horaire (
    id_site VARCHAR(20) NOT NULL REFERENCES app.site (id_site),
    heure TIMESTAMPTZ NOT NULL,          -- début de l'heure
    consommation_kwh NUMERIC(12, 3),
    pic_kw NUMERIC(10, 2),
    moyenne_kw NUMERIC(10, 2),
    nb_mesures INTEGER NOT NULL CHECK (nb_mesures >= 0),
    nb_imputees INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (id_site, heure),
    CHECK (nb_imputees BETWEEN 0 AND nb_mesures)
);

-- Prédictions : chaque exécution du modèle ajoute des lignes (historique
-- conservé pour comparer prédit et réel, et mesurer le drift)
CREATE TABLE IF NOT EXISTS gold.prediction (
    id_site VARCHAR(20) NOT NULL REFERENCES app.site (id_site),
    heure_prevue TIMESTAMPTZ NOT NULL,
    calculee_le TIMESTAMPTZ NOT NULL DEFAULT now(),
    consommation_prevue_kwh NUMERIC(12, 3) NOT NULL,
    pic_prevu BOOLEAN NOT NULL DEFAULT false,
    version_modele VARCHAR(50) NOT NULL,  -- version enregistrée dans MLflow
    PRIMARY KEY (id_site, heure_prevue, calculee_le)
);

-- Métriques du modèle, écrites par le service modèle à chaque évaluation
CREATE TABLE IF NOT EXISTS gold.performance_modele (
    version_modele VARCHAR(50) NOT NULL,
    evalue_le TIMESTAMPTZ NOT NULL DEFAULT now(),
    mae NUMERIC(12, 4),
    rmse NUMERIC(12, 4),
    score_drift NUMERIC(8, 4),
    PRIMARY KEY (version_modele, evalue_le)
);

-- État des capteurs (alimenté par l'ETL depuis GET /api/v1/sensors/status)
CREATE TABLE IF NOT EXISTS gold.etat_capteur (
    id_site VARCHAR(20) NOT NULL REFERENCES app.site (id_site),
    capteur VARCHAR(20) NOT NULL
    CHECK (
        capteur IN (
            'consumption', 'electrical', 'temperature', 'humidity', 'network'
        )
    ),
    statut VARCHAR(10) NOT NULL CHECK (statut IN ('ok', 'failing')),
    en_panne_jusqu_a TIMESTAMPTZ,
    mis_a_jour_le TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id_site, capteur)
);

-- Alertes : fin IS NULL signifie que l'alerte est en cours
CREATE TABLE IF NOT EXISTS gold.alerte (
    id_alerte BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_site VARCHAR(20) NOT NULL REFERENCES app.site (id_site),
    -- alert_id de l'API Mock, évite les doublons
    id_externe VARCHAR(100) UNIQUE,
    source VARCHAR(10) NOT NULL  -- noqa: RF04
    CHECK (source IN ('api_mock', 'etl', 'modele')),
    type VARCHAR(20) NOT NULL  -- noqa: RF04
    CHECK (
        type IN (
            'spike',
            'threshold',
            'anomaly',
            'outage',
            'sensor',
            'predicted_peak'
        )
    ),
    severite VARCHAR(10) NOT NULL CHECK (
        severite IN ('low', 'medium', 'high', 'critical')
    ),
    message TEXT,
    debut TIMESTAMPTZ NOT NULL,
    fin TIMESTAMPTZ,
    valeur NUMERIC(10, 2),               -- maximum atteint pendant l'alerte
    seuil NUMERIC(10, 2),
    CHECK (fin IS null OR fin >= debut),
    -- seules les alertes de l'API Mock ont un identifiant externe
    CHECK ((source = 'api_mock') = (id_externe IS NOT null))
);

-- Accès rapide aux alertes en cours d'un site
CREATE INDEX IF NOT EXISTS idx_alerte_en_cours
ON gold.alerte (id_site) WHERE fin IS null;

-- Recommandations produites par les règles métier
CREATE TABLE IF NOT EXISTS gold.recommandation (
    id_recommandation BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_site VARCHAR(20) NOT NULL REFERENCES app.site (id_site),
    id_alerte BIGINT REFERENCES gold.alerte (id_alerte) ON DELETE SET NULL,
    regle VARCHAR(50) NOT NULL,   -- règle qui a produit la recommandation
    titre VARCHAR(200) NOT NULL,
    description TEXT,
    date_creation TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recommandation_site
ON gold.recommandation (id_site, date_creation DESC);

COMMIT;
