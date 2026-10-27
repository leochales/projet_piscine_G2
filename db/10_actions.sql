-- =============================================================================
-- EnerVision : actions du dashboard (écran « Alertes et recommandations »)
-- 10 : décisions sur les recommandations et prises en compte des alertes
--
-- Ces actions sont des données de l'application : elles vont dans app, où l'API
-- écrit. gold reste en lecture seule pour l'API, car l'ETL et le modèle le
-- recalculent : une action stockée dans gold pourrait être écrasée.
--
-- Une ligne par action, jamais modifiée. Une recommandation n'est décidée
-- qu'une fois (16_decision_unique.sql) et une alerte n'est prise en compte
-- qu'une fois. L'état courant est donné par les vues.
--
-- Après 05_gold.sql (clés étrangères vers gold) et 06_roles.sql (droits par
-- défaut du compte api sur app, appliqués aux tables créées ici).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Décisions sur les recommandations (boutons « Accepter » et « Refuser »)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app.decision_recommandation (
    id_decision BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_recommandation BIGINT NOT NULL
    REFERENCES gold.recommandation (id_recommandation),
    -- Identifiant Keycloak de l'utilisateur qui a décidé
    id_utilisateur UUID NOT NULL REFERENCES app.utilisateur (id),
    statut VARCHAR(10) NOT NULL CHECK (statut IN ('acceptee', 'refusee')),
    decide_le TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dernière décision d'une recommandation (vue etat_recommandation)
CREATE INDEX IF NOT EXISTS idx_decision_recommandation
ON app.decision_recommandation (
    id_recommandation, decide_le DESC, id_decision DESC
);


-- -----------------------------------------------------------------------------
-- Prises en compte des alertes (bouton « Prise en compte »)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app.prise_en_compte_alerte (
    id_prise_en_compte BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Une seule prise en compte par alerte (US7) : la base refuse la deuxième,
    -- même si deux utilisateurs cliquent en même temps (l'API répond 409)
    id_alerte BIGINT NOT NULL UNIQUE REFERENCES gold.alerte (id_alerte),
    -- Identifiant Keycloak de l'utilisateur qui a pris l'alerte en compte
    id_utilisateur UUID NOT NULL REFERENCES app.utilisateur (id),
    prise_le TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- -----------------------------------------------------------------------------
-- Historique non modifiable : l'API ajoute des lignes mais ne peut ni les
-- modifier ni les supprimer (06_roles.sql lui donne ces droits par défaut sur
-- toutes les tables de app : on les retire ici).
-- -----------------------------------------------------------------------------
REVOKE UPDATE, DELETE, TRUNCATE
ON app.decision_recommandation, app.prise_en_compte_alerte
FROM api;


-- -----------------------------------------------------------------------------
-- État courant, croisé avec gold : ce que lit le dashboard
-- -----------------------------------------------------------------------------

-- La vue app.recommandation_etat est définie dans 14_gold_gain_fourchette.sql :
-- elle lit le gain estimé, ajouté à gold.recommandation par le script 14.

-- Une ligne par alerte de gold, avec sa prise en compte si elle existe.
CREATE OR REPLACE VIEW app.alerte_etat AS
SELECT
    a.id_alerte,
    a.id_site,
    a.source,
    a.type,
    a.severite,
    a.message,
    a.debut,
    a.fin,
    a.valeur,
    a.seuil,
    p.id_utilisateur AS prise_par,
    p.prise_le,
    p.id_alerte IS NOT null AS prise_en_compte
FROM gold.alerte AS a
LEFT JOIN app.prise_en_compte_alerte AS p ON a.id_alerte = p.id_alerte;

-- Les vues se lisent seulement : l'écriture passe par les tables d'historique
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON app.alerte_etat
FROM api;

COMMIT;
