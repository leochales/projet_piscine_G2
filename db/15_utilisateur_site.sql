-- =============================================================================
-- EnerVision : sites attribués à un utilisateur
-- 15 : un compte CONSULT-SITE ou GESTION-SITE ne voit que les sites listés ici,
--      parmi ceux de son client. Les rôles *-CLIENT voient tous les sites du
--      client, sans ligne ici (api/auth.py, Perimetre).
--
-- Rejouable sans effet (db/tools/migrate.sh).
--
-- Droits : ceux de 06_roles.sql pour les tables de app (lecture et écriture
-- par l'API, qui attribuera les sites à la création des comptes).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS app.utilisateur_site (
    id_utilisateur UUID NOT NULL
    REFERENCES app.utilisateur (id) ON DELETE CASCADE,
    id_site VARCHAR(20) NOT NULL
    REFERENCES app.site (id_site) ON DELETE CASCADE,
    date_creation TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id_utilisateur, id_site)
);

-- Utilisateurs d'un site (la clé primaire sert la recherche par utilisateur)
CREATE INDEX IF NOT EXISTS idx_utilisateur_site_site ON app.utilisateur_site (
    id_site
);

COMMIT;
