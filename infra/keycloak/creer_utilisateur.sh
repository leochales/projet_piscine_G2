#!/usr/bin/env bash
# =============================================================================
# EnerVision : créer un compte sans passer par l'API
#
# Crée l'utilisateur dans Keycloak (realm enervision) avec un rôle et un mot de
# passe provisoire, puis l'enregistre dans app.utilisateur avec le même
# identifiant (sub). Sans cette ligne, l'API refuse l'utilisateur (403) : c'est
# elle qui dit à quelle entreprise il appartient.
#
# Usage normal : les comptes sont créés depuis le dashboard (POST /api/utilisateurs,
# SMARTOPS-84). Ce script sert seulement :
#   - à créer le premier administrateur EnerVision d'un environnement ;
#   - à créer des comptes de test en local ou en dev.
#
# Depuis la racine du dépôt :
#   infra/keycloak/creer_utilisateur.sh <email> <prénom> <nom> <rôle> <client>
#
#   <rôle>   : CONSULT-SITE, CONSULT-CLIENT, GESTION-SITE ou GESTION-CLIENT
#   <client> : nom du client dans app.client (ex. "Démo EnerVision"),
#              ou --enervision pour un administrateur EnerVision (sans client)
#
# Exemples :
#   # Compte de test en local, rattaché au client de démonstration
#   infra/keycloak/creer_utilisateur.sh marie@test.fr Marie Martin CONSULT-CLIENT "Démo EnerVision"
#
#   # Premier administrateur EnerVision sur la VM (environnement prod)
#   COMPOSE="docker compose -p enervision-prod" \
#     infra/keycloak/creer_utilisateur.sh admin@enervision.fr Alex Admin GESTION-CLIENT --enervision
#
# Variables facultatives :
#   COMPOSE                  commande Compose (défaut : docker compose -f compose-local.yml)
#   KEYCLOAK_ADMIN           compte administrateur Keycloak (sinon demandé)
#   KEYCLOAK_ADMIN_PASSWORD  son mot de passe (sinon demandé, sans affichage)
#
# Le mot de passe provisoire est affiché une seule fois : Keycloak impose de le
# changer à la première connexion.
# =============================================================================
set -Eeuo pipefail

# Git Bash (Windows) convertit les chemins comme /opt/... en chemins Windows
export MSYS_NO_PATHCONV=1

ROLES_AUTORISES=(CONSULT-SITE CONSULT-CLIENT GESTION-SITE GESTION-CLIENT)
REALM=enervision

if [ "$#" -ne 5 ]; then
    sed -n '/^# Depuis la racine/,/^# changer/p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

EMAIL=$1
PRENOM=$2
NOM=$3
ROLE=$4
CLIENT=$5

# shellcheck disable=SC2206 # découpage voulu : COMPOSE contient plusieurs mots
COMPOSE_CMD=(${COMPOSE:-docker compose -f compose-local.yml})

erreur() {
    echo "Erreur : $*" >&2
    exit 1
}

role_valide=false
for role_autorise in "${ROLES_AUTORISES[@]}"; do
    [ "$ROLE" = "$role_autorise" ] && role_valide=true
done
[ "$role_valide" = true ] || erreur "rôle inconnu : $ROLE (attendu : ${ROLES_AUTORISES[*]})"
if [[ ! "$EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
    erreur "e-mail invalide : $EMAIL"
fi

# Requête SQL dans le conteneur db, avec le compte propriétaire de la base.
# Les valeurs passent par des variables psql (:'nom'), jamais collées dans le SQL.
psql_db() {
    "${COMPOSE_CMD[@]}" exec -T db sh -c \
        'psql -X -q -t -A -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' \
        psql "$@" | tr -d '\r'
}

kcadm() {
    "${COMPOSE_CMD[@]}" exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@" | tr -d '\r'
}

# --- 1. Client de rattachement -----------------------------------------------
if [ "$CLIENT" = "--enervision" ]; then
    ID_CLIENT=""
    echo "Administrateur EnerVision : aucun client"
else
    ID_CLIENT=$(psql_db -v client="$CLIENT" <<'SQL'
SELECT id_client FROM app.client WHERE nom = :'client';
SQL
    )
    [ -n "$ID_CLIENT" ] || erreur "client introuvable dans app.client : $CLIENT"
    echo "Client : $CLIENT (id_client = $ID_CLIENT)"
fi

# --- 2. Connexion à Keycloak (compte administrateur du realm master) ---------
if [ -z "${KEYCLOAK_ADMIN:-}" ]; then
    read -r -p "Compte administrateur Keycloak : " KEYCLOAK_ADMIN
fi
if [ -z "${KEYCLOAK_ADMIN_PASSWORD:-}" ]; then
    read -r -s -p "Mot de passe de $KEYCLOAK_ADMIN : " KEYCLOAK_ADMIN_PASSWORD
    echo
fi
kcadm config credentials --server http://localhost:8080/auth --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

# --- 3. Création du compte dans Keycloak -------------------------------------
# -i : renvoie l'identifiant du compte, qui sera le sub de ses jetons.
# Échoue (409) si l'e-mail est déjà utilisé.
ID_UTILISATEUR=$(kcadm create users -r "$REALM" -i \
    -s "username=$EMAIL" -s "email=$EMAIL" \
    -s "firstName=$PRENOM" -s "lastName=$NOM" \
    -s enabled=true -s emailVerified=true)
[ -n "$ID_UTILISATEUR" ] || erreur "Keycloak n'a pas renvoyé d'identifiant"

# Si une étape suivante échoue, on supprime le compte : pas de compte à moitié créé
annuler() {
    echo "Échec : suppression du compte Keycloak $ID_UTILISATEUR" >&2
    kcadm delete "users/$ID_UTILISATEUR" -r "$REALM" || true
}
trap annuler ERR

# --- 4. Mot de passe provisoire et rôle --------------------------------------
# 20 caractères alphanumériques (politique du realm : 12 minimum)
MOT_DE_PASSE=$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
kcadm set-password -r "$REALM" --userid "$ID_UTILISATEUR" \
    --new-password "$MOT_DE_PASSE" --temporary
kcadm add-roles -r "$REALM" --uid "$ID_UTILISATEUR" --rolename "$ROLE"

# --- 5. Rattachement dans app.utilisateur ------------------------------------
psql_db -v id="$ID_UTILISATEUR" -v id_client="$ID_CLIENT" <<'SQL'
INSERT INTO app.utilisateur (id, id_client)
VALUES (:'id', NULLIF(:'id_client', '')::BIGINT);
SQL

trap - ERR

echo
echo "Compte créé : $EMAIL ($ROLE)"
echo "Identifiant (sub) : $ID_UTILISATEUR"
echo "Mot de passe provisoire, à changer à la première connexion : $MOT_DE_PASSE"
