#!/usr/bin/env bash
# =============================================================================
# EnerVision : mots de passe des comptes des services
# 03 : lit les mots de passe dans les variables d'environnement du conteneur
#      (alimentées par les secrets GitHub au déploiement) et les applique.
#      Aucun mot de passe n'est écrit dans le dépôt.
# =============================================================================
set -euo pipefail

for var in ETL_DB_PASSWORD MODEL_DB_PASSWORD API_DB_PASSWORD BACKUP_DB_PASSWORD; do
    if [ -z "${!var:-}" ]; then
        echo "Variable manquante : $var" >&2
        exit 1
    fi
done

# Les mots de passe passent par des variables psql (:'var'), échappées par psql
psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v etl_pwd="$ETL_DB_PASSWORD" \
     -v model_pwd="$MODEL_DB_PASSWORD" \
     -v api_pwd="$API_DB_PASSWORD" \
     -v backup_pwd="$BACKUP_DB_PASSWORD" <<'EOSQL'
ALTER ROLE etl    PASSWORD :'etl_pwd';
ALTER ROLE model  PASSWORD :'model_pwd';
ALTER ROLE api    PASSWORD :'api_pwd';
ALTER ROLE backup PASSWORD :'backup_pwd';
EOSQL
