-- =============================================================================
-- EnerVision : un site rattaché appartient au client de l'utilisateur
-- 16 : clés étrangères composées sur app.utilisateur_site (SMARTOPS-96)
--
-- 15 crée la table des sites attribués aux rôles -SITE. L'API vérifie déjà que
-- le site appartient au client du compte (api/services/comptes.py, lier_site).
-- Ce script fait garantir la même règle par la base, même si l'API a un bug :
-- la table reçoit id_client, et deux clés étrangères composées partagent cette
-- colonne :
--   (id_utilisateur, id_client) doit exister dans app.utilisateur ;
--   (id_site, id_client) doit exister dans app.site.
-- Un rattachement à un site d'un autre client est donc refusé.
--
-- Rejouable sans effet (db/tools/migrate.sh) : sur une base qui a déjà la
-- table de 15, ajoute la colonne, la remplit depuis app.utilisateur et
-- remplace les clés étrangères simples ; sur une base à jour, ne fait rien.
-- Si un rattachement existant viole la règle, la migration échoue : à corriger
-- à la main (supprimer la ligne), car on ne sait pas lequel des deux a tort.
--
-- Conséquences voulues :
--   - un administrateur EnerVision (sans client) ne peut pas être rattaché à un
--     site (id_client NOT NULL) ; il voit déjà tous les clients ;
--   - pas de ON UPDATE : changer le client d'un utilisateur ou d'un site qui a
--     des rattachements est refusé, il faut d'abord retirer ces rattachements.
--
-- Les droits ne changent pas : l'API lit et écrit toutes les tables de app
-- (ALTER DEFAULT PRIVILEGES, 06_roles.sql).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Cibles des clés étrangères composées
-- -----------------------------------------------------------------------------
-- id et id_site sont déjà uniques (clés primaires) : ces contraintes ne
-- changent rien aux données, elles servent seulement de cible aux clés
-- étrangères. ADD CONSTRAINT n'a pas de IF NOT EXISTS : on vérifie d'abord
-- dans pg_constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_utilisateur_id_client'
          AND conrelid = 'app.utilisateur'::regclass
    ) THEN
        ALTER TABLE app.utilisateur
        ADD CONSTRAINT uq_utilisateur_id_client UNIQUE (id, id_client);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_site_id_client'
          AND conrelid = 'app.site'::regclass
    ) THEN
        ALTER TABLE app.site
        ADD CONSTRAINT uq_site_id_client UNIQUE (id_site, id_client);
    END IF;
END
$$;

-- -----------------------------------------------------------------------------
-- Colonne id_client, remplie pour les rattachements existants
-- -----------------------------------------------------------------------------
ALTER TABLE app.utilisateur_site ADD COLUMN IF NOT EXISTS id_client BIGINT;

UPDATE app.utilisateur_site AS us
SET id_client = u.id_client
FROM app.utilisateur AS u
WHERE u.id = us.id_utilisateur AND us.id_client IS NULL;

ALTER TABLE app.utilisateur_site ALTER COLUMN id_client SET NOT NULL;

-- -----------------------------------------------------------------------------
-- Clés étrangères composées, à la place des clés simples de 15
-- -----------------------------------------------------------------------------
-- ON DELETE CASCADE, comme en 15 : le rattachement n'a plus de sens sans
-- l'utilisateur ou sans le site.
ALTER TABLE app.utilisateur_site
DROP CONSTRAINT IF EXISTS utilisateur_site_id_utilisateur_fkey,
DROP CONSTRAINT IF EXISTS utilisateur_site_id_site_fkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_utilisateur_site_utilisateur'
          AND conrelid = 'app.utilisateur_site'::regclass
    ) THEN
        ALTER TABLE app.utilisateur_site
        ADD CONSTRAINT fk_utilisateur_site_utilisateur
        FOREIGN KEY (id_utilisateur, id_client)
        REFERENCES app.utilisateur (id, id_client) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_utilisateur_site_site'
          AND conrelid = 'app.utilisateur_site'::regclass
    ) THEN
        ALTER TABLE app.utilisateur_site
        ADD CONSTRAINT fk_utilisateur_site_site
        FOREIGN KEY (id_site, id_client)
        REFERENCES app.site (id_site, id_client) ON DELETE CASCADE;
    END IF;
END
$$;

COMMENT ON TABLE app.utilisateur_site IS
'Sites visibles par un utilisateur -SITE (CONSULT-SITE, GESTION-SITE). '
'Le site appartient toujours au client de l''utilisateur.';
COMMENT ON COLUMN app.utilisateur_site.id_client IS
'Client commun à l''utilisateur et au site, '
'vérifié par les deux clés étrangères';

COMMIT;
