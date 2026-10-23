-- =============================================================================
-- Tests de la consommation horaire (db/12_gold_horaire.sql) et des droits des
-- comptes etl et model sur gold.consommation_horaire
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur) : un site et deux heures de silver
INSERT INTO app.client (nom) VALUES ('Client test horaire');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES (
    'SITE-H',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test horaire'
    ),
    'Site test horaire',
    'office',
    500
);

-- Heure close (10:00 à 10:59), 60 minutes dans silver :
--   - 10:00 et 10:01 imputées (100 kW) ;
--   - 10:30 mesurée à 160 kW (le pic) ;
--   - 10:58 et 10:59 sans consommation (trou trop long pour être imputé) ;
--   - les autres mesurées à 100 kW.
-- Heure en cours (11:00 à 11:09) : 10 minutes mesurées à 120 kW.
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-H' AS id_site,
    t.ts AS horodatage,
    CASE
        WHEN t.n IN (0, 1, 58, 59) THEN NULL
        WHEN t.n = 30 THEN 160
        ELSE 100
    END AS consumption_kw_raw,
    CASE
        WHEN t.n IN (58, 59) THEN NULL
        WHEN t.n = 30 THEN 160
        ELSE 100
    END AS consumption_kw_imputed,
    CASE
        WHEN t.n IN (0, 1) THEN 'linear_interpolation' ELSE 'none'
    END AS imputation_method,
    CASE WHEN t.n IN (58, 59) THEN 'critical' ELSE 'good' END AS data_quality,
    CASE
        WHEN t.n IN (58, 59) THEN ARRAY['no_reading'] ELSE ARRAY[]::text[]
    END AS null_reasons
FROM (
    SELECT
        n,
        '2026-01-01 10:00+00'::timestamptz + n * interval '1 minute' AS ts
    FROM generate_series(0, 59) AS n
) AS t;

INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    data_quality
)
SELECT
    'SITE-H' AS id_site,
    '2026-01-01 11:00+00'::timestamptz + n * interval '1 minute' AS horodatage,
    120 AS consumption_kw_raw,
    120 AS consumption_kw_imputed,
    'good' AS data_quality
FROM generate_series(0, 9) AS n;

-- À partir d'ici, tout est exécuté avec les droits du compte etl
SET ROLE etl;

-- 1. Premier calcul : les deux heures sont agrégées
DO $$
DECLARE
    nb BIGINT;
    h gold.consommation_horaire;
BEGIN
    SELECT heures INTO nb FROM gold.calculer_consommation_horaire()
    WHERE id_site = 'SITE-H';
    ASSERT nb = 2, format('2 heures attendues, %s écrites', nb);

    SELECT * INTO h FROM gold.consommation_horaire
    WHERE id_site = 'SITE-H' AND heure = '2026-01-01 10:00+00';
    -- 57 × 100 + 160 = 5 860 kW·min, soit 97,667 kWh
    ASSERT h.consommation_kwh = 97.667, format('kWh : %s', h.consommation_kwh);
    ASSERT h.pic_kw = 160, format('pic : %s', h.pic_kw);
    ASSERT h.moyenne_kw = 101.03, format('moyenne : %s', h.moyenne_kw);
    ASSERT h.nb_mesures = 58, format('nb_mesures : %s', h.nb_mesures);
    ASSERT h.nb_imputees = 2, format('nb_imputees : %s', h.nb_imputees);
    ASSERT h.taux_couverture = 0.967, format('couverture : %s', h.taux_couverture);
    ASSERT h.heure_complete, 'l''heure 10:00 est complète';

    SELECT * INTO h FROM gold.consommation_horaire
    WHERE id_site = 'SITE-H' AND heure = '2026-01-01 11:00+00';
    ASSERT h.consommation_kwh = 20.000, format('kWh en cours : %s', h.consommation_kwh);
    ASSERT h.taux_couverture = 0.167, format('couverture en cours : %s', h.taux_couverture);
    ASSERT NOT h.heure_complete, 'l''heure 11:00 est en cours';
    RAISE NOTICE 'OK 1 : kWh, pic, moyenne, couverture et heure complète';
END
$$;

-- 2. L'heure en cours avance : seules les deux dernières heures sont
--    recalculées, et les valeurs suivent silver
RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    data_quality
)
SELECT
    'SITE-H' AS id_site,
    '2026-01-01 11:10+00'::timestamptz + n * interval '1 minute' AS horodatage,
    120 AS consumption_kw_raw,
    120 AS consumption_kw_imputed,
    'good' AS data_quality
FROM generate_series(0, 49) AS n;
SET ROLE etl;

DO $$
DECLARE
    nb BIGINT;
    h gold.consommation_horaire;
    total BIGINT;
BEGIN
    SELECT heures INTO nb FROM gold.calculer_consommation_horaire()
    WHERE id_site = 'SITE-H';
    ASSERT nb = 2, format('2 heures recalculées attendues, %s', nb);

    SELECT count(*) INTO total FROM gold.consommation_horaire
    WHERE id_site = 'SITE-H';
    ASSERT total = 2, format('pas de doublon attendu, %s lignes', total);

    SELECT * INTO h FROM gold.consommation_horaire
    WHERE id_site = 'SITE-H' AND heure = '2026-01-01 11:00+00';
    ASSERT h.consommation_kwh = 120.000, format('kWh : %s', h.consommation_kwh);
    ASSERT h.taux_couverture = 1, format('couverture : %s', h.taux_couverture);
    ASSERT h.heure_complete, 'l''heure 11:00 est maintenant complète';
    RAISE NOTICE 'OK 2 : recalcul rejouable, heure en cours mise à jour';
END
$$;

-- 3. Le modèle lit les agrégats mais ne peut pas les modifier
RESET ROLE;
SET ROLE model;

DO $$
DECLARE
    total BIGINT;
BEGIN
    SELECT count(*) INTO total FROM gold.consommation_horaire
    WHERE id_site = 'SITE-H';
    ASSERT total = 2, format('le modèle doit lire 2 heures, %s', total);

    BEGIN
        UPDATE gold.consommation_horaire SET pic_kw = 0 WHERE id_site = 'SITE-H';
        RAISE EXCEPTION 'le modèle ne doit pas pouvoir modifier gold.consommation_horaire';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;  -- refus attendu
    END;

    BEGIN
        PERFORM gold.calculer_consommation_horaire();
        RAISE EXCEPTION 'le modèle ne doit pas pouvoir lancer le calcul';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;  -- refus attendu
    END;
    RAISE NOTICE 'OK 3 : le modèle lit les agrégats, sans pouvoir les écrire';
END
$$;

RESET ROLE;
ROLLBACK;
