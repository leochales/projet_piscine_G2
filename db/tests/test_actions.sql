-- =============================================================================
-- Tests des actions du dashboard (db/10_actions.sql) et des droits du
-- compte api
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
--
-- Pas dans db/ directement : PostgreSQL ne doit pas l'exécuter au démarrage.
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur)
INSERT INTO app.client (nom) VALUES ('Client test');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES (
    'SITE-T',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test'
    ),
    'Site test',
    'bureaux',
    500
);

INSERT INTO app.utilisateur (id) VALUES
('00000000-0000-0000-0000-00000000000a'),
('00000000-0000-0000-0000-00000000000b');

INSERT INTO gold.alerte (id_site, source, type, severite, debut) VALUES
('SITE-T', 'etl', 'spike', 'high', now()),
('SITE-T', 'etl', 'threshold', 'low', now());

INSERT INTO gold.recommandation (id_site, regle, titre)
VALUES ('SITE-T', 'test', 'Décaler la production'),
('SITE-T', 'test', 'Sans décision');

-- Identifiants des données de test, lus par les blocs ci-dessous
CREATE TEMP TABLE ids ON COMMIT DROP AS
SELECT
    (
        SELECT min(id_recommandation) FROM gold.recommandation
        WHERE id_site = 'SITE-T'
    ) AS reco,
    (
        SELECT max(id_recommandation) FROM gold.recommandation
        WHERE id_site = 'SITE-T'
    ) AS reco_seule,
    (
        SELECT min(id_alerte) FROM gold.alerte
        WHERE id_site = 'SITE-T'
    ) AS alerte,
    (
        SELECT max(id_alerte) FROM gold.alerte
        WHERE id_site = 'SITE-T'
    ) AS alerte_seule;
GRANT SELECT ON ids TO api;

-- À partir d'ici, tout est exécuté avec les droits du compte api
SET ROLE api;

-- 1. L'API enregistre des décisions : la dernière l'emporte.
--    (Même transaction, donc même now() : l'identifiant départage les
--    ex aequo.)
INSERT INTO app.decision_recommandation (
    id_recommandation, id_utilisateur, statut
)
VALUES (
    (SELECT reco FROM ids),
    '00000000-0000-0000-0000-00000000000a',
    'acceptee'
);
INSERT INTO app.decision_recommandation (
    id_recommandation, id_utilisateur, statut
)
VALUES (
    (SELECT reco FROM ids),
    '00000000-0000-0000-0000-00000000000b',
    'refusee'
);

DO $$
DECLARE
    etat app.recommandation_etat;
BEGIN
    SELECT re.* INTO etat FROM app.recommandation_etat AS re, ids WHERE re.id_recommandation = ids.reco;
    ASSERT etat.statut = 'refusee', 'la dernière décision doit être « refusee »';
    ASSERT etat.decide_par = '00000000-0000-0000-0000-00000000000b', 'mauvais décideur';

    SELECT re.* INTO etat FROM app.recommandation_etat AS re, ids WHERE re.id_recommandation = ids.reco_seule;
    ASSERT etat.statut = 'proposee' AND etat.decide_par IS NULL,
        'une recommandation sans décision doit être « proposee »';
    RAISE NOTICE 'OK 1 : décisions enregistrées, état courant = dernière décision';
END
$$;

-- 2. L'API enregistre une prise en compte ; la deuxième est refusée (US7).
INSERT INTO app.prise_en_compte_alerte (id_alerte, id_utilisateur)
VALUES (
    (SELECT alerte FROM ids),
    '00000000-0000-0000-0000-00000000000a'
);

DO $$
DECLARE
    etat app.alerte_etat;
BEGIN
    BEGIN
        INSERT INTO app.prise_en_compte_alerte (id_alerte, id_utilisateur)
        SELECT alerte, '00000000-0000-0000-0000-00000000000b' FROM ids;
        RAISE EXCEPTION 'une deuxième prise en compte devrait être refusée';
    EXCEPTION WHEN unique_violation THEN
        NULL;  -- refus attendu : l'API répondra 409
    END;

    SELECT ae.* INTO etat FROM app.alerte_etat AS ae, ids WHERE ae.id_alerte = ids.alerte;
    ASSERT etat.prise_en_compte, 'l''alerte doit être prise en compte';
    ASSERT etat.prise_par = '00000000-0000-0000-0000-00000000000a',
        'prise_par doit être l''utilisateur de la prise en compte';

    SELECT ae.* INTO etat FROM app.alerte_etat AS ae, ids WHERE ae.id_alerte = ids.alerte_seule;
    ASSERT NOT etat.prise_en_compte AND etat.prise_par IS NULL,
        'une alerte sans action ne doit pas être prise en compte';
    RAISE NOTICE 'OK 2 : prise en compte enregistrée, deuxième refusée';
END
$$;

-- 3. Opérations interdites au compte api, et contraintes de données
DO $$
DECLARE
    interdites CONSTANT TEXT[] := ARRAY[
        -- historique non modifiable
        'UPDATE app.decision_recommandation SET statut = ''acceptee''',
        'DELETE FROM app.decision_recommandation',
        'UPDATE app.prise_en_compte_alerte SET prise_le = now()',
        'DELETE FROM app.prise_en_compte_alerte',
        -- aucun nouveau droit d'écriture sur gold
        'UPDATE gold.recommandation SET titre = titre',
        'UPDATE gold.alerte SET message = message',
        'INSERT INTO gold.recommandation (id_site, regle, titre) VALUES (''SITE-T'', ''x'', ''x'')'
    ];
    requete TEXT;
BEGIN
    FOREACH requete IN ARRAY interdites LOOP
        BEGIN
            EXECUTE requete;
            RAISE EXCEPTION 'devrait être refusé au compte api : %', requete;
        EXCEPTION WHEN insufficient_privilege THEN
            NULL;  -- refus attendu
        END;
    END LOOP;
    RAISE NOTICE 'OK 3 : historique non modifiable et gold en lecture seule pour api';

    BEGIN
        INSERT INTO app.decision_recommandation (id_recommandation, id_utilisateur, statut)
        SELECT reco, '00000000-0000-0000-0000-00000000000a', 'peut-etre' FROM ids;
        RAISE EXCEPTION 'un statut inconnu devrait être refusé';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO app.decision_recommandation (id_recommandation, id_utilisateur, statut)
        SELECT reco, '00000000-0000-0000-0000-0000000000ff', 'acceptee' FROM ids;
        RAISE EXCEPTION 'un utilisateur inconnu devrait être refusé';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO app.prise_en_compte_alerte (id_alerte, id_utilisateur)
        VALUES (-1, '00000000-0000-0000-0000-00000000000a');
        RAISE EXCEPTION 'une alerte inconnue devrait être refusée';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;
    RAISE NOTICE 'OK 4 : statut, utilisateur et alerte contrôlés';
END
$$;

RESET ROLE;

ROLLBACK;
