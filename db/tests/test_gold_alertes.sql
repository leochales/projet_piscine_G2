-- =============================================================================
-- Tests des alertes de l'ETL (db/16_gold_alertes.sql) et des droits des
-- comptes etl et model
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur) : trois sites de 200 kW
--   - SITE-A et SITE-C : seuil par défaut (90 %, soit 180 kW), critique à
--     220 kW ;
--   - SITE-B : seuil à 100 % (200 kW), comme un datacenter.
INSERT INTO app.client (nom) VALUES ('Client test alertes');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw)
SELECT
    v.id_site,
    c.id_client,
    v.nom,
    'office' AS type,  -- noqa: RF04
    200 AS capacite_kw
FROM app.client AS c
CROSS JOIN (
    VALUES
    ('SITE-A', 'Site test seuil'),
    ('SITE-B', 'Site test capteurs'),
    ('SITE-C', 'Site test limites')
) AS v (id_site, nom)
WHERE c.nom = 'Client test alertes';

UPDATE app.site SET seuil_alerte_pct = 100
WHERE id_site = 'SITE-B';

-- Une minute de silver par ligne : (site, minute, kW mesurés, raisons)
-- SITE-A, en kW (seuil 180) :
--   10:00-10:01  190 190     2 minutes hautes : pas d'alerte
--   10:02        100
--   10:03-10:06  190 190 · 190   la minute 10:05 manque (ignorée) :
--                                3 minutes hautes, alerte dès 10:03
--   10:07        230         critique (≥ 110 % de 200 kW)
--   10:08-10:09  100 190     baisse brève : l'alerte reste en cours
--   10:10-10:12  100 100 100 3 minutes basses : fin à 10:10
-- SITE-B, 95 % de la capacité (190 kW), sous son seuil de 100 % :
--   10:00-10:01  capteur de consommation en panne 2 minutes : pas d'alerte
--   10:02        normal
--   10:03-10:06  capteur électrique en panne, sauf 10:05 non transmise
--                (ignorée) : alerte medium dès 10:03, toujours en cours
-- SITE-C, valeurs limites et trois pics sur la même série :
--   10:00-10:02  180 180 219.99  pile 90 % : alerte dès 10:00, high
--                                (juste sous 110 %)
--   10:03-10:05  179.99 × 3      juste sous 90 % : fin à 10:03
--   10:06-10:08  200 220 200     pile 110 % : 2e alerte, critical
--   10:09-10:11  100 × 3         fin à 10:09
--   10:12-10:14  190 × 3         3e alerte, toujours en cours
CREATE TEMPORARY TABLE minutes_test (
    id_site VARCHAR,
    n_minute INT,
    kw NUMERIC,
    raisons TEXT[]
) ON COMMIT DROP;

INSERT INTO minutes_test VALUES
('SITE-A', 0, 190, '{}'),
('SITE-A', 1, 190, '{}'),
('SITE-A', 2, 100, '{}'),
('SITE-A', 3, 190, '{}'),
('SITE-A', 4, 190, '{}'),
('SITE-A', 5, null, '{no_reading}'),
('SITE-A', 6, 190, '{}'),
('SITE-A', 7, 230, '{}'),
('SITE-A', 8, 100, '{}'),
('SITE-A', 9, 190, '{}'),
('SITE-A', 10, 100, '{}'),
('SITE-A', 11, 100, '{}'),
('SITE-A', 12, 100, '{}'),
('SITE-B', 0, null, '{consumption_sensor_failure}'),
('SITE-B', 1, null, '{consumption_sensor_failure}'),
('SITE-B', 2, 190, '{}'),
('SITE-B', 3, 190, '{electrical_sensor_failure}'),
('SITE-B', 4, 190, '{electrical_sensor_failure}'),
('SITE-B', 5, null, '{no_reading}'),
('SITE-B', 6, 190, '{electrical_sensor_failure}'),
('SITE-C', 0, 180, '{}'),
('SITE-C', 1, 180, '{}'),
('SITE-C', 2, 219.99, '{}'),
('SITE-C', 3, 179.99, '{}'),
('SITE-C', 4, 179.99, '{}'),
('SITE-C', 5, 179.99, '{}'),
('SITE-C', 6, 200, '{}'),
('SITE-C', 7, 220, '{}'),
('SITE-C', 8, 200, '{}'),
('SITE-C', 9, 100, '{}'),
('SITE-C', 10, 100, '{}'),
('SITE-C', 11, 100, '{}'),
('SITE-C', 12, 190, '{}'),
('SITE-C', 13, 190, '{}'),
('SITE-C', 14, 190, '{}');

INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    id_site,
    '2026-01-01 10:00+00'::TIMESTAMPTZ + n_minute * INTERVAL '1 minute'
        AS horodatage,
    kw AS consumption_kw_raw,
    kw AS consumption_kw_imputed,
    'none' AS imputation_method,
    CASE WHEN raisons = '{}' THEN 'good' ELSE 'partial' END AS data_quality,
    raisons AS null_reasons
FROM minutes_test;

-- 1. Seuil : 3 minutes hautes, valeur nulle ignorée, baisse brève, fin
--    après 3 minutes basses, critique à 110 %. Seuil par site.
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    SELECT count(*) INTO nb FROM gold.detecter_alertes()
    WHERE id_site IN ('SITE-A', 'SITE-B');
    ASSERT nb = 2, format('2 alertes attendues, %s', nb);

    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-A' AND type = 'threshold';
    ASSERT nb = 1, format('une seule alerte de seuil pour SITE-A, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-A' AND type = 'threshold';
    ASSERT a.debut = '2026-01-01 10:03+00', format('début : %s', a.debut);
    ASSERT a.fin = '2026-01-01 10:10+00', format('fin : %s', a.fin);
    ASSERT a.valeur = 230, format('valeur : %s', a.valeur);
    ASSERT a.seuil = 180, format('seuil : %s', a.seuil);
    ASSERT a.severite = 'critical', format('sévérité : %s', a.severite);
    ASSERT a.source = 'etl' AND a.capteur IS null, 'source etl, sans capteur';

    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-B' AND type = 'threshold';
    ASSERT nb = 0, 'SITE-B sous son seuil de 100 % : pas d''alerte';
    RAISE NOTICE 'OK 1 : seuil par site, 3 minutes, null ignoré, fin, critique';
END
$$;

-- 2. Capteurs : 2 minutes de panne ne suffisent pas, 3 oui (minute non
--    transmise ignorée), alerte en cours tant que la panne dure
DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-B' AND capteur = 'consumption';
    ASSERT nb = 0, '2 minutes de panne : pas d''alerte';

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-B' AND capteur = 'electrical';
    ASSERT a.type = 'sensor', format('type : %s', a.type);
    ASSERT a.severite = 'medium', format('sévérité : %s', a.severite);
    ASSERT a.debut = '2026-01-01 10:03+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'panne toujours en cours';
    ASSERT a.valeur IS null AND a.seuil IS null, 'ni valeur ni seuil';
    RAISE NOTICE 'OK 2 : panne de capteur après 3 minutes, en cours';
END
$$;

-- 3. Rejouer ne change rien, puis 3 minutes sans panne ferment l'alerte
--    capteur (la même ligne, pas une nouvelle)
DO $$
DECLARE
    nb BIGINT;
BEGIN
    SELECT count(*) INTO nb FROM gold.detecter_alertes()
    WHERE id_site IN ('SITE-A', 'SITE-B');
    ASSERT nb = 0, format('rien à réécrire attendu, %s', nb);
    RAISE NOTICE 'OK 3 : rejouable sans effet';
END
$$;

RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-B' AS id_site,
    '2026-01-01 10:07+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    190 AS consumption_kw_raw,
    190 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 2) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    SELECT count(*) INTO nb FROM gold.detecter_alertes()
    WHERE id_site = 'SITE-B';
    ASSERT nb = 1, format('1 alerte mise à jour attendue, %s', nb);

    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-B' AND capteur = 'electrical';
    ASSERT nb = 1, format('toujours une seule ligne, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-B' AND capteur = 'electrical';
    ASSERT a.fin = '2026-01-01 10:07+00', format('fin : %s', a.fin);
    RAISE NOTICE 'OK 4 : capteur réparé, même alerte fermée';
END
$$;

-- 5. Valeurs limites : 90 % et 110 % pile comptent, juste en dessous non.
--    Plusieurs pics sur la même série, le dernier toujours en cours.
DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-C' AND type = 'threshold';
    ASSERT nb = 3, format('3 alertes de seuil pour SITE-C, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-C' AND debut = '2026-01-01 10:00+00';
    ASSERT a.fin = '2026-01-01 10:03+00', format('fin 1 : %s', a.fin);
    ASSERT a.valeur = 219.99, format('valeur 1 : %s', a.valeur);
    ASSERT a.severite = 'high', format('sévérité 1 : %s', a.severite);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-C' AND debut = '2026-01-01 10:06+00';
    ASSERT a.fin = '2026-01-01 10:09+00', format('fin 2 : %s', a.fin);
    ASSERT a.severite = 'critical', format('sévérité 2 : %s', a.severite);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-C' AND debut = '2026-01-01 10:12+00';
    ASSERT a.fin IS null, 'pic 3 toujours en cours';
    ASSERT a.severite = 'high', format('sévérité 3 : %s', a.severite);
    RAISE NOTICE 'OK 5 : 90 %% et 110 %% pile, plusieurs pics, pic en cours';
END
$$;

-- 6. Le modèle lit le seuil des sites mais ne peut pas lancer la détection
RESET ROLE;
SET ROLE model;

DO $$
DECLARE
    seuil NUMERIC;
BEGIN
    SELECT seuil_alerte_pct INTO seuil FROM app.site WHERE id_site = 'SITE-B';
    ASSERT seuil = 100, format('seuil lu par le modèle : %s', seuil);

    BEGIN
        PERFORM gold.detecter_alertes();
        RAISE EXCEPTION 'le modèle ne doit pas pouvoir lancer la détection';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;  -- refus attendu
    END;
    RAISE NOTICE 'OK 6 : le modèle lit le seuil, sans lancer la détection';
END
$$;

RESET ROLE;
ROLLBACK;
