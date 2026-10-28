-- =============================================================================
-- EnerVision : remise à zéro de la démo
--
-- Une prise en compte d'alerte ou une décision sur une recommandation est
-- définitive (US7, l'API répond 409 à la deuxième). Avant chaque prise de la
-- démo, ce script retire celles des alertes encore en cours : ces alertes
-- retrouvent leur bouton « Prise en compte », leurs recommandations les
-- boutons « Accepter » et « Refuser ». Les actions sur des alertes terminées
-- restent : c'est l'historique.
--
-- Le pic de db/demo/pic.sql continue : une prise ratée se refait aussitôt.
-- db/demo/fin_pic.sql l'arrête à la fin du tournage.
--
-- Avec le compte admin PostgreSQL (le compte api ne peut pas supprimer ces
-- lignes, 10_actions.sql) :
--   docker exec -i postgres \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/demo/reset.sql
-- =============================================================================

BEGIN;

DELETE FROM app.prise_en_compte_alerte AS p
USING gold.alerte AS a
WHERE p.id_alerte = a.id_alerte AND a.fin IS null;

DELETE FROM app.decision_recommandation AS d
USING gold.recommandation AS r, gold.alerte AS a
WHERE
    d.id_recommandation = r.id_recommandation
    AND r.id_alerte = a.id_alerte
    AND a.fin IS null;

COMMIT;
