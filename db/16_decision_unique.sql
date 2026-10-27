-- =============================================================================
-- EnerVision : une seule décision par recommandation
-- 16 : une recommandation acceptée ou refusée le reste (US7, pas de changement
--      d'avis). La base refuse la deuxième décision, même si deux utilisateurs
--      cliquent en même temps : l'API répond 409.
--
-- La vue app.recommandation_etat (14) prend toujours la dernière décision :
-- avec cet index, c'est la seule.
--
-- Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_recommandation
ON app.decision_recommandation (id_recommandation);

COMMIT;
