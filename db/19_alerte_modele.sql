-- =============================================================================
-- EnerVision : alertes de pic prévu du modèle (SMARTOPS-103)
-- 19 : une seule alerte du modèle en cours par site et par type.
--
-- Le modèle (model/alerte_pic.py) écrit chaque heure, après ses prévisions,
-- une alerte predicted_peak par site dont le pic prévu atteint le seuil
-- d'alerte. Un passage suivant met à jour l'alerte en cours (INSERT ... ON
-- CONFLICT sur cet index) au lieu d'en créer une autre, même si deux
-- prévisions tournent en même temps. Une alerte terminée (fin renseignée)
-- reste dans l'historique et ne bloque pas la suivante.
--
-- Les droits ne changent pas : le compte model lit, ajoute et modifie
-- gold.alerte (06_roles.sql).
--
-- Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_alerte_modele_en_cours
ON gold.alerte (id_site, type)
WHERE source = 'modele' AND fin IS null;

COMMENT ON COLUMN gold.alerte.valeur_le IS
'Moment du maximum (valeur) : minute du pic mesuré (threshold de l''ETL), '
'ou heure du plus fort pic prévu (predicted_peak du modèle)';

COMMIT;
