-- =============================================================================
-- EnerVision : gain des recommandations et fourchette des prédictions
-- 14 : colonnes demandées par le wireframe du dashboard (SMARTOPS-90)
--   - écran 3 : « gain estimé : 380 € » par recommandation, et les
--     « économies réalisées » ;
--   - écran 2 : fourchette autour de la prévision (« 1 790 (1 700 – 1 870) »).
--
-- Rejouable sans effet (db/tools/migrate.sh) : met à niveau une base créée
-- avant ce changement, et ne fait rien sur une base à jour.
--
-- Les droits ne changent pas : les nouvelles colonnes suivent ceux de leur
-- table (06_roles.sql). L'ETL écrit le gain, le modèle écrit la fourchette,
-- l'API lit les deux.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Gain estimé des recommandations (calculé par l'ETL, SMARTOPS-40)
-- -----------------------------------------------------------------------------
ALTER TABLE gold.recommandation
ADD COLUMN IF NOT EXISTS gain_estime_eur NUMERIC(10, 2)
CHECK (gain_estime_eur >= 0),
ADD COLUMN IF NOT EXISTS periode_gain VARCHAR(10)
CHECK (periode_gain IN ('unique', 'semaine'));

COMMENT ON COLUMN gold.recommandation.gain_estime_eur IS
'Économie attendue en euros si la recommandation est appliquée '
'(NULL si non estimée)';
COMMENT ON COLUMN gold.recommandation.periode_gain IS
'unique : gain obtenu une fois. semaine : gain obtenu chaque semaine';

-- Un gain a toujours une période, et inversement.
-- ADD CONSTRAINT n'a pas de IF NOT EXISTS : on vérifie avant de l'ajouter.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'recommandation_gain_periode_check'
          AND conrelid = 'gold.recommandation'::regclass
    ) THEN
        ALTER TABLE gold.recommandation
        ADD CONSTRAINT recommandation_gain_periode_check
        CHECK ((gain_estime_eur IS NULL) = (periode_gain IS NULL));
    END IF;
END
$$;


-- -----------------------------------------------------------------------------
-- Fourchette des prédictions (calculée par le modèle, SMARTOPS-33)
--
-- Les bornes sont facultatives : les prédictions déjà en base n'en ont pas,
-- et la prévision de référence (SMARTOPS-30) peut ne pas en calculer.
-- -----------------------------------------------------------------------------
ALTER TABLE gold.prediction
ADD COLUMN IF NOT EXISTS consommation_basse_kwh NUMERIC(12, 3),
ADD COLUMN IF NOT EXISTS consommation_haute_kwh NUMERIC(12, 3);

COMMENT ON COLUMN gold.prediction.consommation_basse_kwh IS
'Borne basse de la prévision, NULL si le modèle ne donne pas de fourchette';
COMMENT ON COLUMN gold.prediction.consommation_haute_kwh IS
'Borne haute de la prévision, NULL si le modèle ne donne pas de fourchette';

-- Les deux bornes ensemble ou aucune, et basse <= prévue <= haute.
-- Les IS NOT NULL sont nécessaires : avec une seule borne, la comparaison
-- vaut NULL, et PostgreSQL accepte un CHECK qui vaut NULL.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'prediction_fourchette_check'
          AND conrelid = 'gold.prediction'::regclass
    ) THEN
        ALTER TABLE gold.prediction
        ADD CONSTRAINT prediction_fourchette_check
        CHECK (
            (consommation_basse_kwh IS NULL AND consommation_haute_kwh IS NULL)
            OR (
                consommation_basse_kwh IS NOT NULL
                AND consommation_haute_kwh IS NOT NULL
                AND consommation_basse_kwh <= consommation_prevue_kwh
                AND consommation_prevue_kwh <= consommation_haute_kwh
            )
        );
    END IF;
END
$$;


-- -----------------------------------------------------------------------------
-- État des recommandations lu par le dashboard, avec le gain
--
-- Une ligne par recommandation de gold. statut = dernière décision,
-- ou 'proposee' tant que personne n'a décidé.
--
-- Cette vue était définie dans 10_actions.sql. Elle est déplacée ici car elle
-- lit des colonnes créées par ce script : migrate.sh rejoue 10 avant 14, la
-- vue ne peut donc pas rester dans 10. Les nouvelles colonnes sont ajoutées
-- à la fin : CREATE OR REPLACE VIEW refuse de changer l'ordre des colonnes
-- d'une vue existante. D'où le noqa : sqlfluff voudrait les colonnes simples
-- (gain, période) avant le calcul du statut.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.recommandation_etat AS
SELECT  -- noqa: ST06
    r.id_recommandation,
    r.id_site,
    r.id_alerte,
    r.regle,
    r.titre,
    r.description,
    r.date_creation,
    d.id_utilisateur AS decide_par,
    d.decide_le,
    coalesce(d.statut, 'proposee') AS statut,
    r.gain_estime_eur,
    r.periode_gain
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


-- -----------------------------------------------------------------------------
-- Économies réalisées par site (écran 3)
--
-- Règle retenue pour le MVP : somme des gains des recommandations dont la
-- dernière décision est « acceptee ». Un gain par semaine est compté une
-- seule fois, quel que soit le temps écoulé depuis l'acceptation.
-- Une recommandation acceptée puis refusée ne compte plus.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.economies_realisees AS
SELECT
    id_site,
    count(*) AS nb_recommandations_acceptees,
    coalesce(sum(gain_estime_eur), 0) AS economies_eur
FROM app.recommandation_etat
WHERE statut = 'acceptee'
GROUP BY id_site;

-- Les vues se lisent seulement : l'écriture passe par les tables d'historique
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON app.recommandation_etat, app.economies_realisees
FROM api;

COMMIT;
