-- =============================================================================
-- Tests des recommandations (db/18_gold_recommandations.sql) et des droits du
-- compte etl
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur) : un site actif, un site inactif
INSERT INTO app.client (nom) VALUES ('Client test recommandations');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw, statut)
SELECT
    v.id_site,
    c.id_client,
    v.nom,
    'office' AS type,  -- noqa: RF04
    500 AS capacite_kw,
    v.statut
FROM app.client AS c
CROSS JOIN (
    VALUES
    ('SITE-R', 'Site test recommandations', 'active'),
    ('SITE-RI', 'Site test inactif', 'inactive')
) AS v (id_site, nom, statut)
WHERE c.nom = 'Client test recommandations';

-- Alertes en cours, une par cas à vérifier, et une alerte terminée. Débuts
-- décalés : l'ETL n'a qu'une alerte par site, type, capteur et début
-- (uq_alerte_etl, db/17_gold_alertes.sql), et un capteur pour une alerte sensor
INSERT INTO gold.alerte (
    id_site, source, type, capteur, severite, message, debut, fin, valeur, seuil
) VALUES
-- Règle exacte (threshold, critical), dépassement de 120 kW
('SITE-R', 'etl', 'threshold', null, 'critical', 'r1', now(), null, 570, 450),
-- Règle du type (threshold, sans sévérité), dépassement de 50 kW
(
    'SITE-R', 'etl', 'threshold', null, 'high', 'r2',
    now() - interval '1 minute', null, 500, 450
),
-- Pic prévu par le modèle, dépassement de 10 kW
(
    'SITE-R', 'modele', 'predicted_peak', null, 'high', 'r3',
    now(), null, 460, 450
),
-- Pas de gain : type sans dépassement de seuil
(
    'SITE-R', 'etl', 'sensor', 'consumption', 'medium', 'r4',
    now(), null, null, null
),
-- Pas de gain : valeur sous le seuil
('SITE-R', 'etl', 'spike', null, 'high', 'r5', now(), null, 400, 450),
-- Alerte terminée : pas de recommandation
(
    'SITE-R', 'etl', 'threshold', null, 'high', 'r6',
    now() - interval '2 minutes', now(), 500, 450
),
-- Site inactif : pas de recommandation
('SITE-RI', 'etl', 'threshold', null, 'high', 'r7', now(), null, 500, 450);

-- 1. Une recommandation par alerte en cours d'un site actif, avec la bonne
--    règle et le bon gain
SET ROLE etl;

DO $$
DECLARE
    creees BIGINT;
    mises_a_jour BIGINT;
    r RECORD;
BEGIN
    SELECT g.creees, g.mises_a_jour INTO creees, mises_a_jour
    FROM gold.generer_recommandations(0.20) AS g;
    ASSERT creees = 5, format('5 recommandations attendues, %s', creees);
    ASSERT mises_a_jour = 0, format('aucune mise à jour attendue, %s', mises_a_jour);

    FOR r IN
        SELECT a.message, rec.regle, rec.gain_estime_eur, rec.periode_gain
        FROM gold.recommandation AS rec
        INNER JOIN gold.alerte AS a ON rec.id_alerte = a.id_alerte
        WHERE rec.id_site = 'SITE-R'
    LOOP
        CASE r.message
            WHEN 'r1' THEN
                ASSERT r.regle = 'threshold_critical', format('r1 : %s', r.regle);
                -- 120 kW × 1 h × 0,20 €
                ASSERT r.gain_estime_eur = 24.00, format('r1 gain : %s', r.gain_estime_eur);
                ASSERT r.periode_gain = 'unique', format('r1 période : %s', r.periode_gain);
            WHEN 'r2' THEN
                ASSERT r.regle = 'threshold', format('r2 : %s', r.regle);
                ASSERT r.gain_estime_eur = 10.00, format('r2 gain : %s', r.gain_estime_eur);
            WHEN 'r3' THEN
                ASSERT r.regle = 'predicted_peak', format('r3 : %s', r.regle);
                ASSERT r.gain_estime_eur = 2.00, format('r3 gain : %s', r.gain_estime_eur);
            WHEN 'r4' THEN
                ASSERT r.regle = 'sensor', format('r4 : %s', r.regle);
                ASSERT r.gain_estime_eur IS null AND r.periode_gain IS null,
                    'r4 : pas de gain attendu';
            WHEN 'r5' THEN
                ASSERT r.regle = 'spike', format('r5 : %s', r.regle);
                ASSERT r.gain_estime_eur IS null, 'r5 : pas de gain sous le seuil';
            ELSE
                RAISE EXCEPTION 'recommandation inattendue pour %', r.message;
        END CASE;
    END LOOP;
    RAISE NOTICE 'OK 1 : règles exacte et par type, gain des dépassements';
END
$$;

-- 2. Rejouer ne crée pas de doublon et ne réécrit rien
DO $$
DECLARE
    creees BIGINT;
    mises_a_jour BIGINT;
BEGIN
    SELECT g.creees, g.mises_a_jour INTO creees, mises_a_jour
    FROM gold.generer_recommandations(0.20) AS g;
    ASSERT creees = 0, format('aucune nouvelle recommandation attendue, %s', creees);
    ASSERT mises_a_jour = 0, format('aucune mise à jour attendue, %s', mises_a_jour);
    RAISE NOTICE 'OK 2 : rejouable sans doublon';
END
$$;

-- 3. Une alerte sans règle de son type prend la règle générique
--    (on retire la règle « outage » le temps du test)
RESET ROLE;
DELETE FROM gold.regle_recommandation
WHERE regle = 'outage';
INSERT INTO gold.alerte (id_site, source, type, severite, message, debut)
VALUES ('SITE-R', 'etl', 'outage', 'high', 'r8', now());
SET ROLE etl;

DO $$
DECLARE
    regle_obtenue VARCHAR;
BEGIN
    PERFORM gold.generer_recommandations(0.20);
    SELECT rec.regle INTO regle_obtenue
    FROM gold.recommandation AS rec
    INNER JOIN gold.alerte AS a ON rec.id_alerte = a.id_alerte
    WHERE a.message = 'r8';
    ASSERT regle_obtenue = 'alerte_generique', format('r8 : %s', regle_obtenue);
    RAISE NOTICE 'OK 3 : règle générique en dernier recours';
END
$$;

-- 4. Tant que personne n'a décidé, la recommandation suit l'alerte ; une
--    recommandation décidée ne change plus. 17_gold_alertes.sql fait passer
--    r2 en critical à 600 kW, et r1, déjà acceptée, monte à 700 kW.
RESET ROLE;
INSERT INTO app.utilisateur (id) VALUES
('00000000-0000-0000-0000-0000000000d1');
INSERT INTO app.decision_recommandation (
    id_recommandation, id_utilisateur, statut
)
SELECT
    rec.id_recommandation,
    '00000000-0000-0000-0000-0000000000d1' AS id_utilisateur,
    'acceptee' AS statut
FROM gold.recommandation AS rec
INNER JOIN gold.alerte AS a ON rec.id_alerte = a.id_alerte
WHERE a.message = 'r1';
UPDATE gold.alerte SET severite = 'critical', valeur = 600
WHERE message = 'r2';
UPDATE gold.alerte SET valeur = 700
WHERE message = 'r1';
SET ROLE etl;

DO $$
DECLARE
    creees BIGINT;
    mises_a_jour BIGINT;
    r RECORD;
BEGIN
    SELECT g.creees, g.mises_a_jour INTO creees, mises_a_jour
    FROM gold.generer_recommandations(0.20) AS g;
    ASSERT creees = 0, format('aucune nouvelle recommandation attendue, %s', creees);
    ASSERT mises_a_jour = 1, format('1 mise à jour attendue (r2), %s', mises_a_jour);

    FOR r IN
        SELECT a.message, rec.regle, rec.titre, rec.gain_estime_eur
        FROM gold.recommandation AS rec
        INNER JOIN gold.alerte AS a ON rec.id_alerte = a.id_alerte
        WHERE a.message IN ('r1', 'r2')
    LOOP
        CASE r.message
            WHEN 'r1' THEN
                -- Acceptée : gain de la décision (120 kW), pas celui de 700 kW
                ASSERT r.gain_estime_eur = 24.00, format('r1 gain : %s', r.gain_estime_eur);
            WHEN 'r2' THEN
                ASSERT r.regle = 'threshold_critical', format('r2 : %s', r.regle);
                ASSERT r.titre = 'Délestage d''urgence', format('r2 titre : %s', r.titre);
                -- 150 kW × 1 h × 0,20 €
                ASSERT r.gain_estime_eur = 30.00, format('r2 gain : %s', r.gain_estime_eur);
        END CASE;
    END LOOP;
    RAISE NOTICE 'OK 4 : suit l''alerte tant que proposée, figée après décision';
END
$$;

-- 5. Le compte etl lit les règles sans pouvoir les modifier, et le modèle ne
--    peut pas générer de recommandations
DO $$
BEGIN
    BEGIN
        UPDATE gold.regle_recommandation SET titre = 'x';
        RAISE EXCEPTION 'etl ne doit pas pouvoir modifier les règles';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;  -- refus attendu
    END;
    RAISE NOTICE 'OK 5 : etl lit les règles sans les modifier';
END
$$;

RESET ROLE;
SET ROLE model;

DO $$
BEGIN
    BEGIN
        PERFORM gold.generer_recommandations(0.20);
        RAISE EXCEPTION 'le modèle ne doit pas pouvoir générer de recommandations';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;  -- refus attendu
    END;
    RAISE NOTICE 'OK 6 : le modèle ne génère pas de recommandations';
END
$$;

RESET ROLE;
ROLLBACK;
