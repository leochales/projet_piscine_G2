-- =============================================================================
-- EnerVision : une seule décision par recommandation
-- 16 : une recommandation acceptée ou refusée le reste (US7, pas de changement
--      d'avis). La base refuse la deuxième décision, même si deux utilisateurs
--      cliquent en même temps : l'API répond 409.
--
-- La vue app.recommandation_etat (14) prend toujours la dernière décision :
-- avec cet index, c'est la seule. Une base créée avant ce script peut déjà
-- avoir plusieurs décisions par recommandation (changements d'avis, alors
-- permis) : seule la dernière, celle que montrait la vue, est gardée avant de
-- créer l'index.
--
-- Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

-- Même ordre que la vue : la plus récente, puis le plus grand identifiant
DELETE FROM app.decision_recommandation AS d
WHERE EXISTS (
    SELECT 1
    FROM app.decision_recommandation AS plus_recente
    WHERE
        plus_recente.id_recommandation = d.id_recommandation
        AND (plus_recente.decide_le, plus_recente.id_decision)
        > (d.decide_le, d.id_decision)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_recommandation
ON app.decision_recommandation (id_recommandation);

COMMIT;
