#!/usr/bin/env bash
# Comptes de démonstration : créés dans Keycloak (realm enervision) et enregistrés dans
# app.utilisateur avec le même identifiant, sinon l'API répond 403 « compte non rattaché ».
#
#   infra/seed/utilisateurs.sh <local|dev> [fichier.csv]
#
# Mot de passe de tous les comptes : DEFAULT_PASSWORD ci-dessous, ou SEED_PASSWORD s'il est
# défini (12 caractères au moins).
#
# local : stack de compose-local.yml ; dev : environnement dev de la VM (enervision-dev).
# Jamais en prod. Rejouable : un compte existant garde son identifiant, reçoit le mot de
# passe, les rôles et le client du fichier (les rôles en trop ne sont pas retirés).
#
# Rien à installer : kcadm.sh tourne dans le conteneur Keycloak, avec l'administrateur
# initial de ses variables d'environnement, et psql dans celui de PostgreSQL.
set -euo pipefail
# Git Bash (Windows) : les chemins des conteneurs (/opt/..., /tmp/...) restent tels quels
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/../.."

case "${1:-}" in
    local) compose=(docker compose -f compose-local.yml) ;;
    dev) compose=(docker compose -p enervision-dev) ;;
    prod)
        echo "Refusé : pas de comptes de démonstration en prod" >&2
        exit 1
        ;;
    *)
        echo "Usage : [SEED_PASSWORD=...] $0 <local|dev> [fichier.csv]" >&2
        exit 2
        ;;
esac
fichier="${2:-infra/seed/utilisateurs.csv}"

# Comptes de démonstration seulement (local et dev, jamais la prod) : connu de l'équipe
DEFAULT_PASSWORD='EnerVision-Demo-2026'
SEED_PASSWORD="${SEED_PASSWORD:-$DEFAULT_PASSWORD}"
# Politique du realm (infra/keycloak/realm-enervision.json) : 12 caractères au moins
if [ "${#SEED_PASSWORD}" -lt 12 ]; then
    echo "SEED_PASSWORD trop court : 12 caractères au moins" >&2
    exit 1
fi

config=/tmp/kcadm-seed.config
kcadm() {
    "${compose[@]}" exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@" --config "$config"
}
# Jeton de session kcadm : effacé du conteneur, même en cas d'échec
trap '"${compose[@]}" exec -T keycloak rm -f "$config"' EXIT

"${compose[@]}" exec -T keycloak sh -c \
    'KC_CLI_PASSWORD="$KC_BOOTSTRAP_ADMIN_PASSWORD" /opt/keycloak/bin/kcadm.sh config credentials \
        --server http://localhost:8080/auth --realm master \
        --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --config "$1"' _ "$config"

# Requête SQL lue sur l'entrée standard, résultat sans mise en forme
psql_app() {
    "${compose[@]}" exec -T db sh -c \
        'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' _ "$@"
}

# Mot de passe envoyé en JSON sur l'entrée standard : il n'apparaît pas dans les commandes
motdepasse=${SEED_PASSWORD//\\/\\\\}
motdepasse=${motdepasse//\"/\\\"}

while IFS=";" read -r -u 3 email prenom nom roles client || [ -n "$email" ]; do
    client=${client%$'\r'}
    [ "$email" = email ] || [ -z "$email" ] && continue

    # Client vérifié avant de toucher à Keycloak : pas de compte créé à moitié.
    # Client vide : administrateur EnerVision (id_client NULL, voit tous les clients).
    id_client=""
    if [ -n "$client" ]; then
        id_client=$(psql_app -v client="$client" <<<"SELECT id_client FROM app.client WHERE nom = :'client';")
        if [ -z "$id_client" ]; then
            echo "$email : client « $client » inconnu (SELECT nom FROM app.client), arrêt" >&2
            exit 1
        fi
    fi

    id=$(kcadm get users -r enervision -q "email=$email" -q exact=true \
        --fields id --format csv --noquotes)
    if [ -z "$id" ]; then
        id=$(kcadm create users -r enervision -i -s "email=$email" \
            -s "firstName=$prenom" -s "lastName=$nom" -s enabled=true -s emailVerified=true)
        etat="créé"
    else
        etat="existant"
    fi

    printf '{"type":"password","value":"%s","temporary":false}' "$motdepasse" \
        | kcadm update "users/$id/reset-password" -r enervision -f -
    role_args=()
    IFS=',' read -ra liste <<<"$roles"
    for role in "${liste[@]}"; do
        role_args+=(--rolename "$role")
    done
    kcadm add-roles -r enervision --uid "$id" "${role_args[@]}"

    psql_app -v id="$id" -v id_client="$id_client" <<'SQL'
INSERT INTO app.utilisateur (id, id_client)
VALUES (CAST(:'id' AS UUID), CAST(NULLIF(:'id_client', '') AS BIGINT))
ON CONFLICT (id) DO UPDATE SET id_client = excluded.id_client;
SQL
    echo "$email : $etat, rôles $roles, client ${client:-aucun (administrateur EnerVision)}"
done 3<"$fichier"
