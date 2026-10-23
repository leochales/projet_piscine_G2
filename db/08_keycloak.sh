#!/usr/bin/env bash
# =============================================================================
# EnerVision : base de données de Keycloak
# 08 : crée la base keycloak et son compte, séparés de la base enervision.
#      Le mot de passe vient de KEYCLOAK_DB_PASSWORD.
# =============================================================================
set -euo pipefail

if [ -z "${KEYCLOAK_DB_PASSWORD:-}" ]; then
    echo "KEYCLOAK_DB_PASSWORD absente : base keycloak non créée" >&2
    exit 0
fi

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
\getenv keycloak_pwd KEYCLOAK_DB_PASSWORD
SELECT 'CREATE ROLE keycloak LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') \gexec
ALTER ROLE keycloak PASSWORD :'keycloak_pwd';
SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak') \gexec
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
-- Sauvegarde : pg_read_all_data (06_roles.sql) donne la lecture des tables, pas la connexion
GRANT CONNECT ON DATABASE keycloak TO backup;
EOSQL
