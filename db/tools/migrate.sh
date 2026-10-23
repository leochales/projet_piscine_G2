#!/usr/bin/env bash
# =============================================================================
# EnerVision : migration de la base
#
# Rejoue, dans l'ordre, tous les scripts de db/ sur une base existante.
# PostgreSQL ne les exécute qu'au premier démarrage (volume vide) : sans ce
# script, une nouvelle table, un nouveau compte ou un nouveau droit n'atteindrait
# jamais une base déjà déployée.
#
# Chaque script de db/ doit donc pouvoir être rejoué sans effet sur une base à
# jour (IF NOT EXISTS, ON CONFLICT DO NOTHING, CREATE OR REPLACE VIEW…). Pour
# modifier une table existante, ajouter un nouveau script numéroté
# (ALTER TABLE … ADD COLUMN IF NOT EXISTS) plutôt que de modifier son CREATE.
#
# Exécuté dans le conteneur db, où db/ est monté sur /docker-entrypoint-initdb.d :
#   docker compose -f compose-local.yml exec db bash /docker-entrypoint-initdb.d/tools/migrate.sh
# Lancé à chaque déploiement (deploy.yml) et rejoué en CI (images.yml).
# Pas dans db/ directement : PostgreSQL l'exécuterait au premier démarrage.
# =============================================================================
set -euo pipefail

# Masque les NOTICE « already exists, skipping » des IF NOT EXISTS
export PGOPTIONS="-c client_min_messages=warning"

# Même ordre et même exécution que l'entrypoint de l'image postgres
for f in /docker-entrypoint-initdb.d/*; do
    case "$f" in
        *.sh)
            echo "== $(basename "$f")"
            bash "$f"
            ;;
        *.sql)
            echo "== $(basename "$f")"
            psql -v ON_ERROR_STOP=1 --no-psqlrc -q \
                 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
            ;;
        # Dossiers (tests/, tools/) : ignorés, comme au premier démarrage
    esac
done

echo "Migration terminée"
