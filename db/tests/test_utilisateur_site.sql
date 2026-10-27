-- =============================================================================
-- Tests du rattachement des utilisateurs à leurs sites
-- (db/15_utilisateur_site.sql et db/16_utilisateur_site_client.sql), et des
-- droits de l'API sur cette table
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur) : deux clients, un site chacun
INSERT INTO app.client (nom) VALUES ('Client test A'), ('Client test B');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES
(
    'SITE-A',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test A'
    ),
    'Site test A',
    'bureaux',
    500
),
(
    'SITE-B',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test B'
    ),
    'Site test B',
    'bureaux',
    500
);

INSERT INTO app.utilisateur (id, id_client) VALUES (
    '00000000-0000-0000-0000-0000000000a1',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test A'
    )
);

-- Administrateur EnerVision : aucun client
INSERT INTO app.utilisateur (id) VALUES
('00000000-0000-0000-0000-0000000000a2');


-- 1. L'API rattache un utilisateur à un site de son client, et le relit
SET ROLE api;

INSERT INTO app.utilisateur_site (id_utilisateur, id_site, id_client) VALUES (
    '00000000-0000-0000-0000-0000000000a1',
    'SITE-A',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test A'
    )
);

DO $$
BEGIN
    IF (
        SELECT count(*) FROM app.utilisateur_site
        WHERE id_utilisateur = '00000000-0000-0000-0000-0000000000a1'
    ) <> 1 THEN
        RAISE EXCEPTION 'l''API devrait relire le rattachement';
    END IF;
END
$$;

RESET ROLE;


-- 2. Rattachements refusés par la base
DO $$
DECLARE
    client_a BIGINT := (SELECT id_client FROM app.client WHERE nom = 'Client test A');
    client_b BIGINT := (SELECT id_client FROM app.client WHERE nom = 'Client test B');
BEGIN
    -- Site d'un autre client, en déclarant le client de l'utilisateur
    BEGIN
        INSERT INTO app.utilisateur_site (id_utilisateur, id_site, id_client)
        VALUES ('00000000-0000-0000-0000-0000000000a1', 'SITE-B', client_a);
        RAISE EXCEPTION 'un site d''un autre client devrait être refusé';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    -- Site d'un autre client, en déclarant le client du site
    BEGIN
        INSERT INTO app.utilisateur_site (id_utilisateur, id_site, id_client)
        VALUES ('00000000-0000-0000-0000-0000000000a1', 'SITE-B', client_b);
        RAISE EXCEPTION 'un utilisateur d''un autre client devrait être refusé';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    -- Administrateur EnerVision : pas de client, donc pas de rattachement
    BEGIN
        INSERT INTO app.utilisateur_site (id_utilisateur, id_site, id_client)
        VALUES ('00000000-0000-0000-0000-0000000000a2', 'SITE-A', NULL);
        RAISE EXCEPTION 'un rattachement sans client devrait être refusé';
    EXCEPTION WHEN not_null_violation THEN
        NULL;
    END;

    -- Changer le client d'un utilisateur rattaché à un site
    BEGIN
        UPDATE app.utilisateur SET id_client = client_b
        WHERE id = '00000000-0000-0000-0000-0000000000a1';
        RAISE EXCEPTION 'changer le client d''un utilisateur rattaché devrait être refusé';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;
END
$$;


-- 3. Supprimer l'utilisateur supprime ses rattachements
DELETE FROM app.utilisateur
WHERE id = '00000000-0000-0000-0000-0000000000a1';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM app.utilisateur_site
        WHERE id_utilisateur = '00000000-0000-0000-0000-0000000000a1'
    ) THEN
        RAISE EXCEPTION 'les rattachements devraient suivre l''utilisateur supprimé';
    END IF;
END
$$;

ROLLBACK;
