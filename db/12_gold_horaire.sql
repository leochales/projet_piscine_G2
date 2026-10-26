-- =============================================================================
-- EnerVision : consommation horaire dans gold (SMARTOPS-25)
-- 12 : couverture de chaque heure, et lecture des agrégats par le modèle.
--
-- Une heure dont il manque des minutes a des kWh sous-estimés : le taux de
-- couverture permet au dashboard de le signaler et au modèle d'écarter ces
-- heures de l'entraînement. Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

ALTER TABLE gold.consommation_horaire
ADD COLUMN IF NOT EXISTS taux_couverture NUMERIC(4, 3) NOT NULL DEFAULT 0
CHECK (taux_couverture BETWEEN 0 AND 1),
ADD COLUMN IF NOT EXISTS heure_complete BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN gold.consommation_horaire.heure IS
'Début de l''heure, en UTC';
COMMENT ON COLUMN gold.consommation_horaire.consommation_kwh IS
'Somme des kW de chaque minute × 1/60 h (valeurs mesurées et imputées)';
COMMENT ON COLUMN gold.consommation_horaire.nb_mesures IS
'Minutes de l''heure ayant une consommation (mesurée ou imputée), 60 au plus';
COMMENT ON COLUMN gold.consommation_horaire.nb_imputees IS
'Parmi nb_mesures, minutes complétées par imputation en silver';
COMMENT ON COLUMN gold.consommation_horaire.taux_couverture IS
'nb_mesures / 60 : sous 1, consommation_kwh est sous-estimée';
COMMENT ON COLUMN gold.consommation_horaire.heure_complete IS
'Vrai quand silver a atteint la dernière minute de l''heure (hh:59)';

-- Le modèle s'entraîne sur ces agrégats plutôt que de recalculer les kWh
-- depuis silver : le dashboard et le modèle voient ainsi les mêmes chiffres
GRANT SELECT ON gold.consommation_horaire TO model;

-- -----------------------------------------------------------------------------
-- Calcul des agrégats, appelé chaque minute par l'ETL (etl/gold_hourly.py)
--
-- Par site actif, recalcule la dernière heure déjà en gold et la précédente
-- (une mesure en retard ou une imputation tardive les modifie encore), puis
-- les heures suivantes. Sur un gold vide, agrège tout silver. Si silver a des
-- minutes plus anciennes que la première heure de gold (amorçage relancé
-- après le début de la collecte, etl/bootstrap.py), repart de la première
-- heure de silver.
--   - consommation_kwh = Σ kW × 1/60 h sur les minutes ayant une consommation
--     (chaque ligne silver est une minute de la grille) ;
--   - heure_complete : silver contient les 60 minutes de l'heure.
-- Le coût en € n'est pas stocké : l'API le calcule à partir des kWh.
--
-- Exécutée avec les droits de l'appelant (compte etl).
-- Retourne le nombre d'heures écrites par site.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.calculer_consommation_horaire()
RETURNS TABLE (id_site VARCHAR, heures BIGINT)
-- plpgsql et non sql : une fonction sql dont la CTE insère dans une table
-- avec clés étrangères échoue quand elle est appelée depuis plpgsql
-- (« AfterTriggerSaveEvent() called outside of query »)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH depart AS (
        SELECT
            s.id_site,
            CASE
                WHEN g.premiere IS null THEN '-infinity'::timestamptz
                WHEN sv.premiere < g.premiere THEN sv.premiere
                ELSE g.derniere - interval '1 hour'
            END AS depuis
        FROM app.site AS s
        -- min et max par site : lus par l'index de la clé primaire
        LEFT JOIN LATERAL (
            SELECT
                min(c.heure) AS premiere,
                max(c.heure) AS derniere
            FROM gold.consommation_horaire AS c
            WHERE c.id_site = s.id_site
        ) AS g ON true
        LEFT JOIN LATERAL (
            SELECT date_trunc('hour', min(r.horodatage), 'UTC') AS premiere
            FROM silver.silver_readings AS r
            WHERE r.id_site = s.id_site
        ) AS sv ON true
        WHERE s.statut = 'active'
    ),

    ecrites AS (
        INSERT INTO gold.consommation_horaire AS c (
            id_site, heure, consommation_kwh, pic_kw, moyenne_kw,
            nb_mesures, nb_imputees, taux_couverture, heure_complete
        )
        SELECT
            r.id_site,
            date_trunc('hour', r.horodatage, 'UTC'),
            round(sum(r.consumption_kw_imputed) / 60, 3),
            max(r.consumption_kw_imputed),
            round(avg(r.consumption_kw_imputed), 2),
            count(r.consumption_kw_imputed),
            count(r.consumption_kw_imputed)
                FILTER (WHERE r.imputation_method <> 'none'),
            round(count(r.consumption_kw_imputed)::numeric / 60, 3),
            count(*) = 60
        FROM silver.silver_readings AS r
        INNER JOIN depart AS d ON r.id_site = d.id_site
        WHERE r.horodatage >= d.depuis
        GROUP BY r.id_site, date_trunc('hour', r.horodatage, 'UTC')
        ON CONFLICT ON CONSTRAINT consommation_horaire_pkey DO UPDATE SET
            consommation_kwh = excluded.consommation_kwh,
            pic_kw = excluded.pic_kw,
            moyenne_kw = excluded.moyenne_kw,
            nb_mesures = excluded.nb_mesures,
            nb_imputees = excluded.nb_imputees,
            taux_couverture = excluded.taux_couverture,
            heure_complete = excluded.heure_complete
        RETURNING c.id_site
    )

    SELECT ecrites.id_site, count(*) FROM ecrites GROUP BY ecrites.id_site;
END;
$$;

REVOKE ALL ON FUNCTION gold.calculer_consommation_horaire() FROM public;
GRANT EXECUTE ON FUNCTION gold.calculer_consommation_horaire() TO etl;

COMMIT;
