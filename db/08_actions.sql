-- =============================================================================
-- EnerVision : actions du dashboard (écran « Alertes et recommandations »)
-- 08 : décisions sur les recommandations et prises en compte des alertes
--
-- Ces actions sont des données de l'application : elles vont dans app, où l'API
-- écrit. gold reste en lecture seule pour l'API, car l'ETL et le modèle le
-- recalculent : une action stockée dans gold pourrait être écrasée.
--
-- Historique complet : une ligne par action, jamais modifiée. L'état courant
-- (dernière décision, première prise en compte) est donné par les vues.
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
    id_alerte BIGINT NOT NULL REFERENCES gold.alerte (id_alerte),
    -- Identifiant Keycloak de l'utilisateur qui a pris l'alerte en compte
    id_utilisateur UUID NOT NULL REFERENCES app.utilisateur (id),
    prise_le TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prise_en_compte_alerte
ON app.prise_en_compte_alerte (id_alerte, prise_le, id_prise_en_compte);


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

-- Une ligne par recommandation de gold. statut = dernière décision,
-- ou 'proposee' tant que personne n'a décidé.
CREATE OR REPLACE VIEW app.recommandation_etat AS
SELECT
    r.id_recommandation,
    r.id_site,
    r.id_alerte,
    r.regle,
    r.titre,
    r.description,
    r.date_creation,
    d.id_utilisateur AS decide_par,
    d.decide_le,
    coalesce(d.statut, 'proposee') AS statut
FROM gold.recommandation AS r
LEFT JOIN LATERAL (
    SELECT
        dr.statut,
        dr.id_utilisateur,
        dr.decide_le
    FROM app.decision_recommandation AS dr
    WHERE dr.id_recommandation = r.id_recommandation
    ORDER BY dr.decide_le DESC, dr.id_decision DESC
    LIMIT 1
) AS d ON true;

-- Une ligne par alerte de gold. Prise en compte dès la première action ;
-- prise_par et prise_le décrivent cette première prise en compte.
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
LEFT JOIN LATERAL (
    SELECT
        pa.id_alerte,
        pa.id_utilisateur,
        pa.prise_le
    FROM app.prise_en_compte_alerte AS pa
    WHERE pa.id_alerte = a.id_alerte
    ORDER BY pa.prise_le, pa.id_prise_en_compte
    LIMIT 1
) AS p ON true;

-- Les vues se lisent seulement : l'écriture passe par les tables d'historique
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON app.recommandation_etat, app.alerte_etat
FROM api;

COMMIT;
