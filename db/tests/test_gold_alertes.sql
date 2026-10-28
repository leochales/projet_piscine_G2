-- =============================================================================
-- Tests des alertes de l'ETL (db/17_gold_alertes.sql) et des droits des
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
    ASSERT a.message IS null, format('message : %s', a.message);

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
    ASSERT a.message = 'Capteur électrique en panne',
    format('message : %s', a.message);
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

-- 7. Seuil abaissé à 50 % (100 kW) : toute la série de SITE-C est en défaut
--    depuis 10:00. L'alerte en cours de 10:12 garde sa ligne (et sa prise
--    en compte), et son début : les alertes de 10:00 et 10:06 restent dans
--    l'historique telles quelles.
RESET ROLE;
UPDATE app.site SET seuil_alerte_pct = 50
WHERE id_site = 'SITE-C';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-C' AND type = 'threshold' AND fin IS null;
    ASSERT nb = 1, format('une seule alerte en cours pour SITE-C, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-C' AND type = 'threshold' AND fin IS null;
    ASSERT a.debut = '2026-01-01 10:12+00', format('début : %s', a.debut);
    ASSERT a.valeur = 220 AND a.severite = 'critical',
    format('valeur %s, sévérité %s', a.valeur, a.severite);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-C' AND debut = '2026-01-01 10:00+00';
    ASSERT a.fin = '2026-01-01 10:03+00', format('fin 10:00 : %s', a.fin);

    SELECT count(*) INTO nb FROM gold.detecter_alertes()
    WHERE id_site = 'SITE-C';
    ASSERT nb = 0, format('rien à réécrire attendu, %s', nb);
    RAISE NOTICE 'OK 7 : seuil abaissé, l''alerte en cours garde sa ligne';
END
$$;

-- 8. Seuil relevé à 100 % (200 kW) : seul le pic de 10:06 reste, déjà
--    terminé. L'alerte en cours de 10:12 n'est plus retrouvée : fermée à
--    10:14.
RESET ROLE;
UPDATE app.site SET seuil_alerte_pct = 100
WHERE id_site = 'SITE-C';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-C' AND type = 'threshold' AND fin IS null;
    ASSERT nb = 0, format('aucune alerte en cours pour SITE-C, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-C' AND debut = '2026-01-01 10:12+00';
    ASSERT a.fin = '2026-01-01 10:14+00', format('fin : %s', a.fin);

    SELECT count(*) INTO nb FROM gold.detecter_alertes()
    WHERE id_site = 'SITE-C';
    ASSERT nb = 0, format('rien à réécrire attendu, %s', nb);
    RAISE NOTICE 'OK 8 : seuil relevé, l''alerte sans défaut est fermée';
END
$$;

-- 9. Site désactivé pendant une panne : capteur de consommation de SITE-B
--    en panne de 10:10 à 10:12, puis site inactive. L'alerte n'est plus
--    calculée : elle est fermée à la dernière minute du site (10:12).
RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-B' AS id_site,
    '2026-01-01 10:10+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    null AS consumption_kw_raw,
    190 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'partial' AS data_quality,
    '{consumption_sensor_failure}'::TEXT[] AS null_reasons
FROM generate_series(0, 2) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-B' AND capteur = 'consumption';
    ASSERT a.debut = '2026-01-01 10:10+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'panne en cours';
END
$$;

RESET ROLE;
UPDATE app.site SET statut = 'inactive'
WHERE id_site = 'SITE-B';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-B' AND capteur = 'consumption';
    ASSERT a.fin = '2026-01-01 10:12+00', format('fin : %s', a.fin);
    RAISE NOTICE 'OK 9 : site désactivé, son alerte en cours est fermée';
END
$$;

-- 10. Un capteur pour toute alerte sensor, et seulement pour elles
RESET ROLE;

DO $$
BEGIN
    BEGIN
        INSERT INTO gold.alerte (id_site, source, type, severite, debut)
        VALUES ('SITE-A', 'etl', 'sensor', 'high', now());
        RAISE EXCEPTION 'alerte sensor sans capteur acceptée';
    EXCEPTION WHEN check_violation THEN
        NULL;  -- refus attendu
    END;

    BEGIN
        INSERT INTO gold.alerte (
            id_site, source, type, capteur, severite, debut
        )
        VALUES ('SITE-A', 'etl', 'threshold', 'consumption', 'high', now());
        RAISE EXCEPTION 'alerte threshold avec capteur acceptée';
    EXCEPTION WHEN check_violation THEN
        NULL;  -- refus attendu
    END;
    -- Les autres sources ne donnent pas de capteur
    INSERT INTO gold.alerte (id_site, source, type, severite, debut)
    VALUES ('SITE-A', 'modele', 'sensor', 'high', now());
    DELETE FROM gold.alerte WHERE source = 'modele';
    RAISE NOTICE 'OK 10 : capteur obligatoire pour sensor (ETL), interdit sinon';
END
$$;

-- 11. Seuil d'un nouveau site : selon son type s'il n'est pas donné,
--     celui donné sinon
INSERT INTO app.site (
    id_site, id_client, nom, type, capacite_kw, seuil_alerte_pct
)
SELECT
    v.id_site,
    c.id_client,
    v.nom,
    v.type_site AS type,  -- noqa: RF04
    200 AS capacite_kw,
    v.seuil AS seuil_alerte_pct
FROM app.client AS c
CROSS JOIN (
    VALUES
    ('SITE-DC', 'Datacenter sans seuil', 'datacenter', null::NUMERIC),
    ('SITE-US', 'Usine sans seuil', 'factory', null),
    ('SITE-BU', 'Bureau sans seuil', 'office', null),
    ('SITE-DC2', 'Datacenter à 95 %', 'datacenter', 95)
) AS v (id_site, nom, type_site, seuil)
WHERE c.nom = 'Client test alertes';

DO $$
DECLARE
    s RECORD;
BEGIN
    FOR s IN
        SELECT id_site, seuil_alerte_pct FROM app.site
        WHERE id_site IN ('SITE-DC', 'SITE-US', 'SITE-BU', 'SITE-DC2')
    LOOP
        ASSERT s.seuil_alerte_pct = CASE s.id_site
            WHEN 'SITE-DC' THEN 100
            WHEN 'SITE-US' THEN 98
            WHEN 'SITE-BU' THEN 90
            WHEN 'SITE-DC2' THEN 95
        END, format('%s : seuil %s', s.id_site, s.seuil_alerte_pct);
    END LOOP;
    RAISE NOTICE 'OK 11 : seuil d''un nouveau site selon son type';
END
$$;

-- 12. Type corrigé : le seuil suit le nouveau type, sauf s'il avait été
--     réglé à la main ou s'il est donné dans la même requête. Un seuil vidé
--     reprend celui du type.
UPDATE app.site SET type = 'datacenter' WHERE id_site = 'SITE-BU';
UPDATE app.site SET type = 'factory' WHERE id_site = 'SITE-DC2';
UPDATE app.site SET type = 'office', seuil_alerte_pct = 97
WHERE id_site = 'SITE-US';
UPDATE app.site SET seuil_alerte_pct = null WHERE id_site = 'SITE-A';

DO $$
DECLARE
    s RECORD;
BEGIN
    FOR s IN
        SELECT id_site, seuil_alerte_pct FROM app.site
        WHERE id_site IN ('SITE-BU', 'SITE-DC2', 'SITE-US', 'SITE-A')
    LOOP
        ASSERT s.seuil_alerte_pct = CASE s.id_site
            WHEN 'SITE-BU' THEN 100
            WHEN 'SITE-DC2' THEN 95
            WHEN 'SITE-US' THEN 97
            WHEN 'SITE-A' THEN 90
        END, format('%s : seuil %s', s.id_site, s.seuil_alerte_pct);
    END LOOP;
    RAISE NOTICE 'OK 12 : le seuil suit le type, sauf réglé à la main';
END
$$;

-- 13. Début décalé : l'alerte en cours garde sa ligne (même identifiant,
--     donc même prise en compte). SITE-D, seuil 180 kW :
--     11:00-11:03 à 190 kW, alerte dès 11:00 ; puis une minute de 10:59
--     arrive en retard (190 kW) : début avancé à 10:59 ; puis 10:59 et
--     11:00 sont réécrites à 100 kW : début reculé à 11:01.
-- 14. Trou de plus de 5 minutes : SITE-E à 190 kW à 10:00, 10:30 et 11:00,
--     pas d'alerte ; puis 11:01 et 11:02 : 3 minutes consécutives, alerte
--     dès 11:00.
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
    ('SITE-D', 'Site test début décalé'),
    ('SITE-E', 'Site test trou')
) AS v (id_site, nom)
WHERE c.nom = 'Client test alertes';

INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    v.id_site,
    v.horodatage,
    190 AS consumption_kw_raw,
    190 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM (
    VALUES
    ('SITE-D', '2026-01-01 11:00+00'::TIMESTAMPTZ),
    ('SITE-D', '2026-01-01 11:01+00'),
    ('SITE-D', '2026-01-01 11:02+00'),
    ('SITE-D', '2026-01-01 11:03+00'),
    ('SITE-E', '2026-01-01 10:00+00'),
    ('SITE-E', '2026-01-01 10:30+00'),
    ('SITE-E', '2026-01-01 11:00+00')
) AS v (id_site, horodatage);

CREATE TEMPORARY TABLE id_test (id_alerte BIGINT) ON COMMIT DROP;
GRANT SELECT, INSERT ON id_test TO etl;
SET ROLE etl;

DO $$
DECLARE
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    INSERT INTO id_test
    SELECT id_alerte FROM gold.alerte
    WHERE id_site = 'SITE-D' AND debut = '2026-01-01 11:00+00' AND fin IS null;
    SELECT count(*) INTO nb FROM id_test;
    ASSERT nb = 1, format('alerte de SITE-D attendue à 11:00, %s', nb);

    SELECT count(*) INTO nb FROM gold.alerte WHERE id_site = 'SITE-E';
    ASSERT nb = 0, format('3 minutes espacées : pas d''alerte, %s', nb);
END
$$;

RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
VALUES (
    'SITE-D', '2026-01-01 10:59+00', 190, 190, 'none', 'good', '{}'
);
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT count(*) INTO nb FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT nb = 1, format('une seule alerte pour SITE-D, %s', nb);

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT a.id_alerte = (SELECT id_alerte FROM id_test),
    'même identifiant après un début avancé';
    ASSERT a.debut = '2026-01-01 10:59+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'toujours en cours';
END
$$;

RESET ROLE;
UPDATE silver.silver_readings
SET consumption_kw_raw = 100, consumption_kw_imputed = 100
WHERE
    id_site = 'SITE-D'
    AND horodatage IN ('2026-01-01 10:59+00', '2026-01-01 11:00+00');
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT count(*) INTO nb FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT nb = 1, format('une seule alerte pour SITE-D, %s', nb);

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT a.id_alerte = (SELECT id_alerte FROM id_test),
    'même identifiant après un début reculé';
    ASSERT a.debut = '2026-01-01 11:01+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'toujours en cours';
    RAISE NOTICE 'OK 13 : début décalé, même alerte (même identifiant)';
END
$$;

RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-E' AS id_site,
    '2026-01-01 11:01+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    190 AS consumption_kw_raw,
    190 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 1) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-E';
    ASSERT a.debut = '2026-01-01 11:00+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'en cours';
    RAISE NOTICE 'OK 14 : un trou de plus de 5 minutes coupe la série';
END
$$;

-- 15. Alerte plus longue que la fenêtre : SITE-D, en cours depuis 11:01,
--     230 kW à 11:04 (critical), puis 190 kW jusqu'à 11:30. Avec une
--     fenêtre de 5 minutes (11:25), l'alerte est reprise de la base : même
--     ligne, même début, même maximum. Puis 3 minutes à 100 kW la ferment.
RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-D' AS id_site,
    '2026-01-01 11:04+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    CASE WHEN n = 0 THEN 230 ELSE 190 END AS consumption_kw_raw,
    CASE WHEN n = 0 THEN 230 ELSE 190 END AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 16) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT a.valeur = 230 AND a.severite = 'critical',
    format('valeur %s, sévérité %s', a.valeur, a.severite);
END
$$;

RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-D' AS id_site,
    '2026-01-01 11:21+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    190 AS consumption_kw_raw,
    190 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 9) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    SELECT count(*) INTO nb FROM gold.detecter_alertes(INTERVAL '5 minutes')
    WHERE id_site = 'SITE-D';
    ASSERT nb = 0, format('alerte reprise sans changement attendue, %s', nb);

    SELECT count(*) INTO nb FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT nb = 1, format('une seule alerte pour SITE-D, %s', nb);

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT a.id_alerte = (SELECT id_alerte FROM id_test), 'même identifiant';
    ASSERT a.debut = '2026-01-01 11:01+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'toujours en cours';
    ASSERT a.valeur = 230 AND a.severite = 'critical',
    format('valeur %s, sévérité %s', a.valeur, a.severite);
END
$$;

RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-D' AS id_site,
    '2026-01-01 11:31+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    100 AS consumption_kw_raw,
    100 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 2) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes(INTERVAL '5 minutes');

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-D';
    ASSERT a.id_alerte = (SELECT id_alerte FROM id_test), 'même identifiant';
    ASSERT a.debut = '2026-01-01 11:01+00', format('début : %s', a.debut);
    ASSERT a.fin = '2026-01-01 11:31+00', format('fin : %s', a.fin);
    ASSERT a.valeur = 230, format('valeur : %s', a.valeur);
    RAISE NOTICE 'OK 15 : alerte plus longue que la fenêtre, reprise de la base';
END
$$;

-- 16. Alerte terminée dont le début se décale : SITE-A, alerte de 10:03 à
--     10:10 ; la minute 10:03 est réécrite à 100 kW. L'alerte commence à
--     10:04 (10:04, 10:06, 10:07 : la minute 10:05 manque) : même ligne,
--     pas de doublon.
RESET ROLE;
UPDATE silver.silver_readings
SET consumption_kw_raw = 100, consumption_kw_imputed = 100
WHERE id_site = 'SITE-A' AND horodatage = '2026-01-01 10:03+00';
INSERT INTO id_test
SELECT id_alerte FROM gold.alerte
WHERE id_site = 'SITE-A' AND type = 'threshold';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT count(*) INTO nb FROM gold.alerte
    WHERE id_site = 'SITE-A' AND type = 'threshold';
    ASSERT nb = 1, format('une seule alerte pour SITE-A, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-A' AND type = 'threshold';
    ASSERT a.id_alerte IN (SELECT id_alerte FROM id_test), 'même identifiant';
    ASSERT a.debut = '2026-01-01 10:04+00', format('début : %s', a.debut);
    ASSERT a.fin = '2026-01-01 10:10+00', format('fin : %s', a.fin);
    RAISE NOTICE 'OK 16 : alerte terminée décalée, même ligne, pas de doublon';
END
$$;

-- 17. Maximum d'une alerte reprise, réécrit plus bas : SITE-E, en cours
--     depuis 11:00 à 190 kW, 210 kW à 11:10, 230 kW à 11:18, jusqu'à 11:20.
--     Avec une fenêtre de 5 minutes (11:15), la minute 11:18 réécrite à
--     195 kW : le maximum redescend à 210 kW (11:10, avant la fenêtre, relu
--     dans silver) et l'alerte n'est plus critical.
-- 18. Puis seuil relevé à 110 % (220 kW) : plus de défaut dans la fenêtre,
--     l'alerte est fermée et garde le seuil qui l'a ouverte (180 kW).
RESET ROLE;
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-E' AS id_site,
    '2026-01-01 11:03+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    v.kw AS consumption_kw_raw,
    v.kw AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 17) AS n
CROSS JOIN LATERAL (
    SELECT CASE n WHEN 7 THEN 210 WHEN 15 THEN 230 ELSE 190 END AS kw
) AS v;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-E';
    ASSERT a.valeur = 230 AND a.valeur_le = '2026-01-01 11:18+00'
    AND a.severite = 'critical',
    format('valeur %s le %s, %s', a.valeur, a.valeur_le, a.severite);
END
$$;

RESET ROLE;
UPDATE silver.silver_readings
SET consumption_kw_raw = 195, consumption_kw_imputed = 195
WHERE id_site = 'SITE-E' AND horodatage = '2026-01-01 11:18+00';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes(INTERVAL '5 minutes');

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-E';
    ASSERT a.debut = '2026-01-01 11:00+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'toujours en cours';
    ASSERT a.valeur = 210 AND a.valeur_le = '2026-01-01 11:10+00',
    format('valeur %s le %s', a.valeur, a.valeur_le);
    ASSERT a.severite = 'high', format('sévérité : %s', a.severite);
    RAISE NOTICE 'OK 17 : maximum réécrit plus bas, relu avant la fenêtre';
END
$$;

RESET ROLE;
UPDATE app.site SET seuil_alerte_pct = 110
WHERE id_site = 'SITE-E';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes(INTERVAL '5 minutes');

    SELECT * INTO a FROM gold.alerte WHERE id_site = 'SITE-E';
    ASSERT a.debut = '2026-01-01 11:00+00', format('début : %s', a.debut);
    ASSERT a.fin = '2026-01-01 11:15+00', format('fin : %s', a.fin);
    ASSERT a.valeur = 210, format('valeur : %s', a.valeur);
    ASSERT a.seuil = 180, format('seuil : %s', a.seuil);
    RAISE NOTICE 'OK 18 : seuil relevé, l''alerte garde le seuil qui l''a ouverte';
END
$$;

RESET ROLE;

-- 19. Mesures refusées (rejected_reading) : ne disent rien du capteur.
--     SITE-F, capteur de consommation en panne à 10:00, 10:01, 10:05 ;
--     10:02-10:04 refusées : ignorées, alerte dès 10:00.
-- 20. Lignes qui se chevauchent et seuil relevé : SITE-F en cours depuis
--     10:00 (L), et une ligne terminée de 10:10 à 10:15 (L2). Le calcul
--     donne une alerte de 10:10 à 10:15 et une de 10:20, en cours. L préfère
--     l'alerte de 10:10 (la plus proche), déjà reprise par L2 : au second
--     tour, L reprend l'alerte de 10:20 et garde son identifiant (et son
--     début, L2 commençant entre les deux).
-- 21. Site sans plus aucune minute dans silver : son alerte en cours est
--     fermée maintenant, et non avec une durée nulle.
INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw)
SELECT 'SITE-F', c.id_client, 'Site test rattachement', 'office', 200
FROM app.client AS c
WHERE c.nom = 'Client test alertes';

INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-F' AS id_site,
    '2026-01-01 10:00+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    null AS consumption_kw_raw,
    190 AS consumption_kw_imputed,
    'none' AS imputation_method,
    'partial' AS data_quality,
    CASE
        WHEN n BETWEEN 2 AND 4 THEN '{rejected_reading}'
        ELSE '{consumption_sensor_failure}'
    END::TEXT[] AS null_reasons
FROM generate_series(0, 5) AS n;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-F' AND capteur = 'consumption';
    ASSERT a.debut = '2026-01-01 10:00+00', format('début : %s', a.debut);
    ASSERT a.fin IS null, 'panne en cours';
    RAISE NOTICE 'OK 19 : mesures refusées ignorées pour un capteur';
END
$$;

RESET ROLE;
DELETE FROM gold.alerte WHERE id_site = 'SITE-F';
DELETE FROM silver.silver_readings WHERE id_site = 'SITE-F';

-- Seuil de SITE-F : 180 kW. 10:00-10:09 à 100 kW, 10:10-10:14 à 190 kW,
-- 10:15-10:19 à 100 kW, 10:20-10:25 à 190 kW
INSERT INTO silver.silver_readings (
    id_site, horodatage, consumption_kw_raw, consumption_kw_imputed,
    imputation_method, data_quality, null_reasons
)
SELECT
    'SITE-F' AS id_site,
    '2026-01-01 10:00+00'::TIMESTAMPTZ + n * INTERVAL '1 minute' AS horodatage,
    v.kw AS consumption_kw_raw,
    v.kw AS consumption_kw_imputed,
    'none' AS imputation_method,
    'good' AS data_quality,
    '{}'::TEXT[] AS null_reasons
FROM generate_series(0, 25) AS n
CROSS JOIN LATERAL (
    SELECT
        CASE
            WHEN n BETWEEN 10 AND 14 OR n >= 20 THEN 190 ELSE 100
        END AS kw
) AS v;

INSERT INTO gold.alerte (
    id_site, source, type, severite, debut, fin, valeur, seuil
)
VALUES
('SITE-F', 'etl', 'threshold', 'high', '2026-01-01 10:00+00', null, 190, 90),
(
    'SITE-F', 'etl', 'threshold', 'high',
    '2026-01-01 10:10+00', '2026-01-01 10:15+00', 190, 180
);

DELETE FROM id_test;
INSERT INTO id_test
SELECT id_alerte FROM gold.alerte
WHERE id_site = 'SITE-F' AND fin IS null;
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
    nb BIGINT;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT count(*) INTO nb FROM gold.alerte WHERE id_site = 'SITE-F';
    ASSERT nb = 2, format('deux alertes pour SITE-F, %s', nb);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-F' AND fin IS null;
    ASSERT a.id_alerte = (SELECT id_alerte FROM id_test), 'même identifiant';
    ASSERT a.debut = '2026-01-01 10:00+00', format('début : %s', a.debut);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-F' AND fin IS NOT null;
    ASSERT a.debut = '2026-01-01 10:10+00'
    AND a.fin = '2026-01-01 10:15+00',
    format('alerte terminée : %s - %s', a.debut, a.fin);
    RAISE NOTICE 'OK 20 : second tour, la ligne en cours garde son identifiant';
END
$$;

RESET ROLE;
DELETE FROM silver.silver_readings WHERE id_site = 'SITE-F';
SET ROLE etl;

DO $$
DECLARE
    a RECORD;
BEGIN
    PERFORM gold.detecter_alertes();

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-F' AND debut = '2026-01-01 10:00+00';
    ASSERT a.fin = now(), format('fin : %s', a.fin);
    RAISE NOTICE 'OK 21 : site sans silver, alerte fermée maintenant';
END
$$;

RESET ROLE;

ROLLBACK;
