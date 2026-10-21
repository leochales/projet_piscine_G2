-- ============================================================
-- EnerVision — Schéma GOLD
-- Script : 03_gold.sql
-- Agrégats métier consommés par la FastAPI et le Dashboard.
--
-- Tables :
--   gold_latest          → dernière mesure par site (dashboard temps réel)
--   gold_hourly          → agrégats horaires (ETL — aggregate.py)
--   gold_predictions     → prévisions ML (predict.py)
--   gold_alerts          → alertes actives
--   etat_capteur         → statut de chaque capteur par site
--   performance_modele   → métriques ML par version de modèle
--   recommandation       → recommandations liées aux alertes
-- ============================================================

SET search_path TO gold;

-- ──────────────────────────────────────────────────────────
-- 1. gold_latest — Dernière mesure connue par site
-- ──────────────────────────────────────────────────────────
-- Utiliser UPSERT (INSERT … ON CONFLICT DO UPDATE) depuis aggregate.py
-- pour maintenir exactement une ligne par site_id.

CREATE TABLE IF NOT EXISTS gold.gold_latest (
    site_id             VARCHAR(10)  NOT NULL,
    site_name           VARCHAR(100) NOT NULL,
    site_type           VARCHAR(30)  NOT NULL,
    capacity_kw         INTEGER      NOT NULL,
    consumption_kw      FLOAT8,
    load_percent        FLOAT4,
    data_quality        VARCHAR(10)  NOT NULL DEFAULT 'good',
    temperature_celsius FLOAT8,
    humidity_percent    FLOAT8,
    facteur_puissance   FLOAT8,                 -- facteur de puissance (0.85 – 0.98 normal)
    null_reasons        TEXT[],                 -- causes de NULL copiées depuis bronze (ex : {'temperature_sensor_failure'})
    last_reading_at     TIMESTAMPTZ  NOT NULL,
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_gold_latest    PRIMARY KEY (site_id),
    CONSTRAINT chk_latest_quality CHECK (data_quality IN ('good','partial','degraded','critical'))
);

COMMENT ON TABLE  gold.gold_latest IS 'Une ligne par site — dernière mesure connue. Maintenue par UPSERT dans aggregate.py. Source principale du dashboard temps réel.';
COMMENT ON COLUMN gold.gold_latest.facteur_puissance IS 'Facteur de puissance issu de silver.power_factor. Plage normale : 0.85 – 0.98.';
COMMENT ON COLUMN gold.gold_latest.null_reasons      IS 'Tableau des causes de NULL retourné par l''API Mock (copié depuis bronze).';

-- ──────────────────────────────────────────────────────────
-- 2. gold_hourly — Agrégats horaires par site
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gold.gold_hourly (
    id                      BIGSERIAL    NOT NULL,
    site_id                 VARCHAR(10)  NOT NULL,
    hour_start              TIMESTAMPTZ  NOT NULL,  -- tronquée à l'heure (date_trunc('hour', ...))

    avg_consumption_kw      FLOAT4,
    max_consumption_kw      FLOAT4,
    min_consumption_kw      FLOAT4,
    avg_load_percent        FLOAT4,
    avg_temperature_celsius FLOAT4,
    avg_humidity_percent    FLOAT4,
    consommation_kwh        FLOAT4,                 -- énergie consommée sur l'heure (kWh = avg_kw × durée réelle)
    cout_eur                FLOAT4,                 -- coût estimé en euros (consommation_kwh × tarif_kwh_eur)

    reading_count           SMALLINT     NOT NULL DEFAULT 0,   -- nb mesures reçues (idéalement 60)
    imputed_count           SMALLINT     NOT NULL DEFAULT 0,   -- nb mesures imputées parmi reading_count
    quality_summary         VARCHAR(10)  NOT NULL DEFAULT 'good',
    -- good | partial | degraded (= qualité dominante sur l'heure)

    computed_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_gold_hourly       PRIMARY KEY (id),
    CONSTRAINT uq_gold_hourly       UNIQUE (site_id, hour_start),
    CONSTRAINT chk_hourly_quality   CHECK (quality_summary IN ('good','partial','degraded'))
);

COMMENT ON TABLE  gold.gold_hourly IS 'Agrégats horaires par site. Produit par aggregate.py toutes les heures à :00.';
COMMENT ON COLUMN gold.gold_hourly.reading_count   IS 'Nombre de mesures silver reçues sur l''heure. Idéalement 60 (1/min). Sert à détecter les trous.';
COMMENT ON COLUMN gold.gold_hourly.imputed_count   IS 'Nombre de mesures imputées parmi reading_count — indicateur de fiabilité de l''agrégat.';
COMMENT ON COLUMN gold.gold_hourly.consommation_kwh IS 'Énergie réellement consommée : avg_consumption_kw × (reading_count / 60). Tient compte des trous de mesure.';
COMMENT ON COLUMN gold.gold_hourly.cout_eur         IS 'Coût estimé en euros : consommation_kwh × tarif_kwh_eur (configurable via TARIF_KWH_EUR).';

CREATE INDEX IF NOT EXISTS idx_gold_hourly_site_ts ON gold.gold_hourly (site_id, hour_start DESC);

-- ──────────────────────────────────────────────────────────
-- 3. gold_predictions — Prévisions du modèle ML
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gold.gold_predictions (
    id                       BIGSERIAL    NOT NULL,
    site_id                  VARCHAR(10)  NOT NULL,
    prediction_for           TIMESTAMPTZ  NOT NULL,  -- heure future prédite

    -- Sorties du modèle Random Forest
    predicted_load_percent   FLOAT4       NOT NULL,  -- sortie directe (normalisée)
    predicted_consumption_kw FLOAT4       NOT NULL,  -- dénormalisé : load_percent * capacity_kw / 100
    consommation_prevue_kwh  FLOAT4,                 -- énergie prévue sur l'heure (kWh)
    pic_prevu                BOOLEAN,                -- TRUE si la prédiction signale un pic de charge

    -- Intervalle de confiance (percentiles p10/p90 des arbres de la forêt)
    confidence_low           FLOAT4,
    confidence_high          FLOAT4,

    model_version            VARCHAR(50)  NOT NULL,  -- identifiant de version du modèle utilisé
    predicted_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_gold_predictions  PRIMARY KEY (id),
    CONSTRAINT uq_gold_pred_site_ts UNIQUE (site_id, prediction_for, model_version),
    CONSTRAINT chk_pred_load        CHECK (predicted_load_percent >= 0.0)
);

COMMENT ON TABLE  gold.gold_predictions IS 'Prévisions ML sur 24h. Produit par predict.py toutes les heures à :05 (après aggregate.py à :00).';
COMMENT ON COLUMN gold.gold_predictions.predicted_load_percent   IS 'Sortie directe du RandomForestRegressor — taux de charge normalisé.';
COMMENT ON COLUMN gold.gold_predictions.predicted_consumption_kw IS 'Dénormalisé pour l''affichage : predicted_load_percent * capacity_kw / 100.';
COMMENT ON COLUMN gold.gold_predictions.consommation_prevue_kwh  IS 'Énergie prévue sur l''heure cible : predicted_consumption_kw × 1h.';
COMMENT ON COLUMN gold.gold_predictions.pic_prevu                IS 'TRUE si predicted_load_percent dépasse le seuil de pic configuré.';
COMMENT ON COLUMN gold.gold_predictions.model_version            IS 'Identifiant de version du modèle (ex : v1.2.0 ou hash de commit).';

CREATE INDEX IF NOT EXISTS idx_gold_pred_site_ts ON gold.gold_predictions (site_id, prediction_for DESC);

-- ──────────────────────────────────────────────────────────
-- 4. gold_alerts — Alertes de consommation
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gold.gold_alerts (
    id              BIGSERIAL    NOT NULL,
    alert_id        VARCHAR(60)  NOT NULL,  -- ID externe API Mock ou généré (ex : ALR-SITE002-1718458320)
    site_id         VARCHAR(10)  NOT NULL,
    alert_timestamp TIMESTAMPTZ  NOT NULL,
    source          VARCHAR(20)  NOT NULL DEFAULT 'silver',  -- 'silver' (seuil interne) | 'api' (API Mock)
    debut           TIMESTAMPTZ,            -- début de la période couverte par l'alerte
    fin             TIMESTAMPTZ,            -- fin de la période (NULL si toujours active)
    severity        VARCHAR(10)  NOT NULL,  -- low | medium | high | critical
    alert_type      VARCHAR(15)  NOT NULL,  -- spike | threshold | anomaly | outage | sensor
    message         TEXT,
    value           FLOAT4,                 -- valeur mesurée ayant déclenché l'alerte (kW)
    threshold       FLOAT4,                 -- seuil configuré (kW)
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    resolved_at     TIMESTAMPTZ,            -- NULL si toujours active
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_gold_alerts       PRIMARY KEY (id),
    CONSTRAINT uq_gold_alerts_extid UNIQUE (alert_id),
    CONSTRAINT chk_alerts_severity  CHECK (severity   IN ('low','medium','high','critical')),
    CONSTRAINT chk_alerts_type      CHECK (alert_type IN ('spike','threshold','anomaly','outage','sensor')),
    CONSTRAINT chk_alerts_source    CHECK (source     IN ('silver','api'))
);

COMMENT ON TABLE  gold.gold_alerts IS 'Alertes de consommation. Alimentée par aggregate.py (seuils internes) et GET /api/v1/alerts.';
COMMENT ON COLUMN gold.gold_alerts.alert_id IS 'Identifiant externe unique. Évite les doublons si l''API Mock retourne plusieurs fois la même alerte.';
COMMENT ON COLUMN gold.gold_alerts.source   IS 'Origine de l''alerte : silver = seuil calculé en interne, api = remontée par l''API Mock.';
COMMENT ON COLUMN gold.gold_alerts.debut    IS 'Début de la période couverte par l''alerte.';
COMMENT ON COLUMN gold.gold_alerts.fin      IS 'Fin de la période. NULL tant que l''alerte est active.';
COMMENT ON COLUMN gold.gold_alerts.is_active IS 'FALSE une fois resolved_at renseigné.';

CREATE INDEX IF NOT EXISTS idx_gold_alerts_site_id  ON gold.gold_alerts (site_id);
CREATE INDEX IF NOT EXISTS idx_gold_alerts_active   ON gold.gold_alerts (is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_gold_alerts_severity ON gold.gold_alerts (severity);

-- ──────────────────────────────────────────────────────────
-- 5. etat_capteur — Statut des capteurs par site
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gold.etat_capteur (
    capteur          VARCHAR(50)  NOT NULL,  -- identifiant du capteur (ex : SITE001-MAIN)
    site_id          VARCHAR(10)  NOT NULL,
    statut           VARCHAR(20)  NOT NULL DEFAULT 'ok',  -- ok | en_panne | degrade
    en_panne_jusqu_a TIMESTAMPTZ,            -- estimation de remise en service (NULL si inconnu)
    mis_a_jour_le    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_etat_capteur    PRIMARY KEY (capteur, site_id),
    CONSTRAINT chk_capteur_statut CHECK (statut IN ('ok', 'en_panne', 'degrade'))
);

COMMENT ON TABLE  gold.etat_capteur IS 'Statut opérationnel de chaque capteur par site. Mis à jour à chaque cycle aggregate.py.';
COMMENT ON COLUMN gold.etat_capteur.capteur          IS 'Identifiant du capteur — convention : {site_id}-MAIN pour le capteur principal.';
COMMENT ON COLUMN gold.etat_capteur.statut           IS 'ok = mesures fiables ; degrade = imputations fréquentes ; en_panne = qualité critical.';
COMMENT ON COLUMN gold.etat_capteur.en_panne_jusqu_a IS 'Estimation de la date de remise en service. NULL si non renseignée.';

CREATE INDEX IF NOT EXISTS idx_etat_capteur_site ON gold.etat_capteur (site_id);

-- ──────────────────────────────────────────────────────────
-- 6. performance_modele — Métriques ML par version de modèle
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gold.performance_modele (
    id             BIGSERIAL    NOT NULL,
    version_modele VARCHAR(50)  NOT NULL,  -- identifiant de version (ex : v1.2.0)
    evalue_le      TIMESTAMPTZ  NOT NULL,  -- date d'évaluation
    mae            FLOAT4,                 -- Mean Absolute Error
    rmse           FLOAT4,                 -- Root Mean Square Error
    score_drift    FLOAT4,                 -- score de drift par rapport à la version précédente

    CONSTRAINT pk_perf_modele PRIMARY KEY (id),
    CONSTRAINT uq_perf_modele UNIQUE (version_modele, evalue_le)
);

COMMENT ON TABLE  gold.performance_modele IS 'Métriques de performance du modèle ML par version. Alimenté par le pipeline d''évaluation (branche model/).';
COMMENT ON COLUMN gold.performance_modele.mae         IS 'Erreur absolue moyenne entre prédiction et consommation réelle (kW).';
COMMENT ON COLUMN gold.performance_modele.rmse        IS 'Racine de l''erreur quadratique moyenne — plus sensible aux gros écarts.';
COMMENT ON COLUMN gold.performance_modele.score_drift IS 'Score de drift : 0.0 = pas de dérive, 1.0 = dérive totale. Déclenche un réentraînement si > 0.3.';

CREATE INDEX IF NOT EXISTS idx_perf_modele_version ON gold.performance_modele (version_modele, evalue_le DESC);

-- ──────────────────────────────────────────────────────────
-- 7. recommandation — Recommandations liées aux alertes
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gold.recommandation (
    id            BIGSERIAL    NOT NULL,
    alert_id      VARCHAR(60)  NOT NULL,   -- référence à gold_alerts.alert_id
    regle         VARCHAR(50)  NOT NULL,   -- règle métier ayant généré la recommandation
    titre         VARCHAR(200) NOT NULL,
    description   TEXT,
    date_creation TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_recommandation PRIMARY KEY (id)
);

COMMENT ON TABLE  gold.recommandation IS 'Recommandations d''action générées automatiquement à partir des alertes actives.';
COMMENT ON COLUMN gold.recommandation.alert_id    IS 'Référence à gold_alerts.alert_id (pas de FK pour tolérer les alertes archivées).';
COMMENT ON COLUMN gold.recommandation.regle       IS 'Règle métier ayant déclenché la recommandation (ex : threshold_high, spike_detected).';
COMMENT ON COLUMN gold.recommandation.description IS 'Description détaillée de l''action recommandée.';

CREATE INDEX IF NOT EXISTS idx_recommandation_alert ON gold.recommandation (alert_id);

-- ── Permissions ────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON gold.gold_latest      TO enervision_worker;
GRANT SELECT, INSERT         ON gold.gold_hourly      TO enervision_worker;
GRANT SELECT, INSERT         ON gold.gold_predictions TO enervision_worker;
GRANT SELECT, INSERT, UPDATE ON gold.gold_alerts      TO enervision_worker;
GRANT SELECT, INSERT, UPDATE ON gold.etat_capteur     TO enervision_worker;
GRANT SELECT, INSERT         ON gold.performance_modele TO enervision_worker;
GRANT SELECT, INSERT         ON gold.recommandation   TO enervision_worker;

GRANT SELECT ON gold.gold_latest       TO enervision_api;
GRANT SELECT ON gold.gold_hourly       TO enervision_api;
GRANT SELECT ON gold.gold_predictions  TO enervision_api;
GRANT SELECT ON gold.gold_alerts       TO enervision_api;
GRANT SELECT ON gold.etat_capteur      TO enervision_api;
GRANT SELECT ON gold.performance_modele TO enervision_api;
GRANT SELECT ON gold.recommandation    TO enervision_api;

GRANT USAGE, SELECT ON SEQUENCE gold.gold_hourly_id_seq        TO enervision_worker;
GRANT USAGE, SELECT ON SEQUENCE gold.gold_predictions_id_seq   TO enervision_worker;
GRANT USAGE, SELECT ON SEQUENCE gold.gold_alerts_id_seq        TO enervision_worker;
GRANT USAGE, SELECT ON SEQUENCE gold.performance_modele_id_seq TO enervision_worker;
GRANT USAGE, SELECT ON SEQUENCE gold.recommandation_id_seq     TO enervision_worker;
