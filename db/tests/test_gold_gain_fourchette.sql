-- =============================================================================
-- Tests du gain des recommandations et de la fourchette des prédictions
-- (db/14_gold_gain_fourchette.sql), et des droits des comptes sur ces colonnes
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur)
INSERT INTO app.client (nom) VALUES ('Client test gain');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES (
    'SITE-G',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test gain'
    ),
    'Site test gain',
    'bureaux',
    500
);

INSERT INTO app.utilisateur (id) VALUES
('00000000-0000-0000-0000-0000000000c1');


-- 1. L'ETL écrit des recommandations avec un gain
SET ROLE etl;

INSERT INTO gold.recommandation (
    id_site, regle, titre, gain_estime_eur, periode_gain
) VALUES
('SITE-G', 'test', 'Acceptée, gain unique', 380, 'unique'),
('SITE-G', 'test', 'Acceptée, gain par semaine', 120, 'semaine'),
('SITE-G', 'test', 'Acceptée puis refusée', 1000, 'unique'),
('SITE-G', 'test', 'Sans décision', 50, 'unique'),
('SITE-G', 'test', 'Acceptée, sans gain', NULL, NULL);

DO $$
BEGIN
    BEGIN
        INSERT INTO gold.recommandation (id_site, regle, titre, gain_estime_eur)
        VALUES ('SITE-G', 'test', 'x', 10);
        RAISE EXCEPTION 'un gain sans période devrait être refusé';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO gold.recommandation (id_site, regle, titre, gain_estime_eur, periode_gain)
        VALUES ('SITE-G', 'test', 'x', -5, 'unique');
        RAISE EXCEPTION 'un gain négatif devrait être refusé';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO gold.recommandation (id_site, regle, titre, gain_estime_eur, periode_gain)
        VALUES ('SITE-G', 'test', 'x', 10, 'mois');
        RAISE EXCEPTION 'une période inconnue devrait être refusée';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
    RAISE NOTICE 'OK 1 : l''ETL écrit le gain, gain et période contrôlés';
END
$$;

RESET ROLE;


-- 2. Le modèle écrit des prédictions avec ou sans fourchette
SET ROLE model;

INSERT INTO gold.prediction (
    id_site, heure_prevue, consommation_prevue_kwh,
    consommation_basse_kwh, consommation_haute_kwh, version_modele
) VALUES
('SITE-G', '2026-01-01 10:00+00', 1790, 1700, 1870, 'test'),
('SITE-G', '2026-01-01 11:00+00', 1790, NULL, NULL, 'test');

DO $$
DECLARE
    -- prévue = 1790 dans chaque cas
    refusees CONSTANT NUMERIC[][] := ARRAY[
        [1800, 1870],   -- borne basse au-dessus de la prévision
        [1700, 1780]    -- borne haute en dessous de la prévision
    ];
    i INT;
BEGIN
    FOR i IN 1 .. array_length(refusees, 1) LOOP
        BEGIN
            INSERT INTO gold.prediction (
                id_site, heure_prevue, consommation_prevue_kwh,
                consommation_basse_kwh, consommation_haute_kwh, version_modele
            ) VALUES (
                'SITE-G', '2026-01-01 12:00+00', 1790,
                refusees[i][1], refusees[i][2], 'test'
            );
            RAISE EXCEPTION 'fourchette [%, %] autour de 1790 devrait être refusée',
                refusees[i][1], refusees[i][2];
        EXCEPTION WHEN check_violation THEN
            NULL;
        END;
    END LOOP;

    BEGIN
        INSERT INTO gold.prediction (
            id_site, heure_prevue, consommation_prevue_kwh,
            consommation_basse_kwh, version_modele
        ) VALUES ('SITE-G', '2026-01-01 12:00+00', 1790, 1700, 'test');
        RAISE EXCEPTION 'une seule borne devrait être refusée';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
    RAISE NOTICE 'OK 2 : le modèle écrit la fourchette, basse <= prévue <= haute';
END
$$;

RESET ROLE;


-- 3. L'API enregistre des décisions et lit les économies réalisées
CREATE TEMP TABLE reco ON COMMIT DROP AS
SELECT
    id_recommandation,
    titre
FROM gold.recommandation
WHERE id_site = 'SITE-G';
GRANT SELECT ON reco TO api;

SET ROLE api;

INSERT INTO app.decision_recommandation (
    id_recommandation, id_utilisateur, statut
)
SELECT
    id_recommandation,
    '00000000-0000-0000-0000-0000000000c1' AS id_utilisateur,
    'acceptee' AS statut
FROM reco
WHERE titre LIKE 'Acceptée%';

-- Même transaction, donc même now() : l'identifiant plus grand l'emporte
INSERT INTO app.decision_recommandation (
    id_recommandation, id_utilisateur, statut
)
SELECT
    id_recommandation,
    '00000000-0000-0000-0000-0000000000c1' AS id_utilisateur,
    'refusee' AS statut
FROM reco
WHERE titre = 'Acceptée puis refusée';

DO $$
DECLARE
    eco app.economies_realisees;
    gain NUMERIC;
BEGIN
    SELECT re.gain_estime_eur INTO gain
    FROM app.recommandation_etat AS re
    INNER JOIN reco AS r ON re.id_recommandation = r.id_recommandation
    WHERE r.titre = 'Acceptée, gain unique';
    ASSERT gain = 380, 'la vue doit exposer le gain estimé';

    SELECT e.* INTO eco FROM app.economies_realisees AS e
    WHERE e.id_site = 'SITE-G';
    -- 380 (unique) + 120 (une semaine, comptée une fois) + 0 (sans gain)
    -- La recommandation refusée en dernier et celle sans décision ne comptent pas
    ASSERT eco.economies_eur = 500,
        format('économies attendues 500, obtenues %s', eco.economies_eur);
    ASSERT eco.nb_recommandations_acceptees = 3,
        format('3 acceptées attendues, obtenues %s', eco.nb_recommandations_acceptees);
    RAISE NOTICE 'OK 3 : économies réalisées = gains des recommandations acceptées';
END
$$;


-- 4. Droits inchangés : l'API lit les nouvelles colonnes mais ne les écrit pas
DO $$
DECLARE
    interdites CONSTANT TEXT[] := ARRAY[
        'UPDATE gold.recommandation SET gain_estime_eur = 0',
        'UPDATE gold.prediction SET consommation_basse_kwh = NULL, consommation_haute_kwh = NULL'
    ];
    requete TEXT;
BEGIN
    PERFORM gain_estime_eur, periode_gain FROM gold.recommandation;
    PERFORM consommation_basse_kwh, consommation_haute_kwh FROM gold.prediction;

    FOREACH requete IN ARRAY interdites LOOP
        BEGIN
            EXECUTE requete;
            RAISE EXCEPTION 'devrait être refusé au compte api : %', requete;
        EXCEPTION WHEN insufficient_privilege THEN
            NULL;  -- refus attendu
        END;
    END LOOP;
    RAISE NOTICE 'OK 4 : l''API lit le gain et la fourchette sans pouvoir les écrire';
END
$$;

RESET ROLE;

ROLLBACK;
