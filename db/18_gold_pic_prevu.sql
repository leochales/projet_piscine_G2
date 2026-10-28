-- =============================================================================
-- EnerVision : pic prévu en kW (SMARTOPS-95)
-- 18 : gold.prediction ne connaît que la consommation moyenne de l'heure et un
--      booléen pic_prevu. Une moyenne horaire dépasse rarement le seuil du
--      site, même quand dix minutes de l'heure sont un vrai pic. Le modèle
--      prédit donc aussi le maximum de l'heure, comparé à
--      app.site.seuil_alerte_pct (pas à un 90 % fixe).
--
-- Rejouable sans effet (db/tools/migrate.sh) : met à niveau une base créée
-- avant ce changement, et ne fait rien sur une base à jour.
--
-- Les droits ne changent pas : les nouvelles colonnes suivent ceux de
-- gold.prediction (06_roles.sql). Le modèle les écrit, l'API les lit.
-- =============================================================================

BEGIN;

-- pic_prevu_kw est facultatif : les prédictions déjà en base n'en ont pas,
-- et une prévision peut ne porter que sur les kWh.
-- La fourchette est facultative, et les deux bornes vont ensemble.
ALTER TABLE gold.prediction
ADD COLUMN IF NOT EXISTS pic_prevu_kw NUMERIC(10, 2),
ADD COLUMN IF NOT EXISTS pic_bas_kw NUMERIC(10, 2),
ADD COLUMN IF NOT EXISTS pic_haut_kw NUMERIC(10, 2);

COMMENT ON COLUMN gold.prediction.pic_prevu_kw IS
'Puissance maximale prévue sur l''heure, en kW. NULL si le modèle ne prédit '
'que la consommation. Le modèle met pic_prevu à vrai quand cette valeur '
'atteint app.site.seuil_alerte_pct pour cent de capacite_kw : 100 pour un '
'datacenter, 98 pour une usine, 90 pour les autres. Le compte model lit '
'cette colonne (GRANT de 17_gold_alertes.sql).';
COMMENT ON COLUMN gold.prediction.pic_bas_kw IS
'Borne basse du pic prévu, NULL si le modèle ne donne pas de fourchette';
COMMENT ON COLUMN gold.prediction.pic_haut_kw IS
'Borne haute du pic prévu, NULL si le modèle ne donne pas de fourchette';

-- Les deux bornes ensemble ou aucune, et basse <= pic prévu <= haute.
-- Un pic prévu sans fourchette reste accepté. Des bornes sans pic prévu
-- sont refusées : la comparaison ne serait pas vérifiable.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'prediction_pic_fourchette_check'
          AND conrelid = 'gold.prediction'::regclass
    ) THEN
        ALTER TABLE gold.prediction
        ADD CONSTRAINT prediction_pic_fourchette_check
        CHECK (
            (pic_bas_kw IS NULL AND pic_haut_kw IS NULL)
            OR (
                pic_prevu_kw IS NOT NULL
                AND pic_bas_kw IS NOT NULL
                AND pic_haut_kw IS NOT NULL
                AND pic_bas_kw <= pic_prevu_kw
                AND pic_prevu_kw <= pic_haut_kw
            )
        );
    END IF;
END
$$;

-- Une puissance prévue ne peut pas être négative. NULL reste accepté :
-- les prédictions déjà en base n'ont pas de pic.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'prediction_pic_positif_check'
          AND conrelid = 'gold.prediction'::regclass
    ) THEN
        ALTER TABLE gold.prediction
        ADD CONSTRAINT prediction_pic_positif_check
        CHECK (
            (pic_prevu_kw IS NULL OR pic_prevu_kw >= 0)
            AND (pic_bas_kw IS NULL OR pic_bas_kw >= 0)
            AND (pic_haut_kw IS NULL OR pic_haut_kw >= 0)
        );
    END IF;
END
$$;

COMMIT;
