-- =============================================================================
-- Tests du pic prévu en kW (db/18_gold_pic_prevu.sql) et des droits des
-- comptes model et api sur ces colonnes
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

INSERT INTO app.client (nom) VALUES ('Client test pic prévu');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES (
    'SITE-P',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test pic prévu'
    ),
    'Site test pic prévu',
    'office',
    500
);


-- 1. Le modèle écrit un pic prévu, avec ou sans fourchette, ou pas de pic
SET ROLE model;

INSERT INTO gold.prediction (
    id_site, heure_prevue, consommation_prevue_kwh, version_modele,
    pic_prevu, pic_prevu_kw, pic_bas_kw, pic_haut_kw
) VALUES
(
    'SITE-P', '2026-01-01 10:00+00', 160, 'test',
    true, 460, 440, 480
),
(
    'SITE-P', '2026-01-01 11:00+00', 140, 'test',
    false, 160, null, null
),
(
    'SITE-P', '2026-01-01 12:00+00', 100, 'test',
    false, null, null, null
);

DO $$
DECLARE
    -- pic prévu = 210 dans chaque cas refusé
    refusees CONSTANT NUMERIC[][] := ARRAY[
        [220, 230],   -- borne basse au-dessus du pic prévu
        [190, 200]    -- borne haute en dessous du pic prévu
    ];
    i INT;
BEGIN
    FOR i IN 1 .. array_length(refusees, 1) LOOP
        BEGIN
            INSERT INTO gold.prediction (
                id_site, heure_prevue, consommation_prevue_kwh, version_modele,
                pic_prevu_kw, pic_bas_kw, pic_haut_kw
            ) VALUES (
                'SITE-P', '2026-01-01 13:00+00', 160, 'test',
                210, refusees[i][1], refusees[i][2]
            );
            RAISE EXCEPTION 'fourchette [%, %] autour de 210 devrait être refusée',
                refusees[i][1], refusees[i][2];
        EXCEPTION WHEN check_violation THEN
            null;
        END;
    END LOOP;

    BEGIN
        INSERT INTO gold.prediction (
            id_site, heure_prevue, consommation_prevue_kwh, version_modele,
            pic_prevu_kw, pic_bas_kw
        ) VALUES ('SITE-P', '2026-01-01 13:00+00', 160, 'test', 210, 190);
        RAISE EXCEPTION 'une seule borne de pic devrait être refusée';
    EXCEPTION WHEN check_violation THEN
        null;
    END;

    BEGIN
        INSERT INTO gold.prediction (
            id_site, heure_prevue, consommation_prevue_kwh, version_modele,
            pic_bas_kw, pic_haut_kw
        ) VALUES ('SITE-P', '2026-01-01 13:00+00', 160, 'test', 190, 230);
        RAISE EXCEPTION 'une fourchette sans pic prévu devrait être refusée';
    EXCEPTION WHEN check_violation THEN
        null;
    END;
    RAISE NOTICE 'OK 1 : le modèle écrit le pic prévu, basse <= prévu <= haute';
END
$$;

RESET ROLE;


-- 2. L'API lit les colonnes et ne peut pas les écrire
SET ROLE api;

DO $$
DECLARE
    pic NUMERIC;
    interdites CONSTANT TEXT[] := ARRAY[
        'UPDATE gold.prediction SET pic_prevu_kw = 0',
        'UPDATE gold.prediction SET pic_bas_kw = null, pic_haut_kw = null'
    ];
    requete TEXT;
BEGIN
    SELECT pic_prevu_kw INTO pic
    FROM gold.prediction
    WHERE id_site = 'SITE-P' AND heure_prevue = '2026-01-01 10:00+00';
    ASSERT pic = 460, format('pic prévu attendu 460, obtenu %s', pic);

    PERFORM pic_prevu_kw, pic_bas_kw, pic_haut_kw FROM gold.prediction;

    FOREACH requete IN ARRAY interdites LOOP
        BEGIN
            EXECUTE requete;
            RAISE EXCEPTION 'devrait être refusé au compte api : %', requete;
        EXCEPTION WHEN insufficient_privilege THEN
            null;
        END;
    END LOOP;
    RAISE NOTICE 'OK 2 : l''API lit le pic prévu sans pouvoir l''écrire';
END
$$;

RESET ROLE;

ROLLBACK;
