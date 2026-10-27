#!/bin/sh
# Sauvegarde nocturne (SMARTOPS-53) : dump de chaque base, envoyé chiffré dans le dépôt
# restic, puis suppression des sauvegardes trop anciennes.
#
# Variables lues :
#   RESTIC_REPOSITORY   dépôt restic (azure:restic-<env>:/ sur la VM, /repo en local)
#   RESTIC_PASSWORD     clé de chiffrement du dépôt : sans elle, les sauvegardes sont illisibles
#   AZURE_ACCOUNT_NAME, AZURE_ACCOUNT_SAS   accès au stockage Azure (dépôt azure: seulement)
#   PGHOST, PGUSER, PGPASSWORD              compte backup (lecture seule, db/06_roles.sql)
#   BACKUP_DATABASES    bases sauvegardées (défaut : enervision keycloak)
#   DEPLOY_ENV          environnement, inscrit comme hôte de chaque sauvegarde
#
# Les bases enervision et keycloak sont sauvegardées ensemble : app.utilisateur.id est le
# sub Keycloak, restaurer l'une sans l'autre rendrait les historiques orphelins.
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY manquant}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD manquant}"
: "${PGPASSWORD:?PGPASSWORD manquant (mot de passe du compte backup)}"

databases="${BACKUP_DATABASES:-enervision keycloak}"
host="enervision-${DEPLOY_ENV:-local}"

# Même format JSON que common/logs.py, pour Loki et Grafana
log() {
    printf '{"timestamp":"%s","level":"%s","service":"backup","logger":"backup","message":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"
}

# Premier lancement : le dépôt n'existe pas encore (code 10 de restic), on le crée.
# Toute autre erreur (réseau, SAS expiré, mauvais mot de passe) arrête la sauvegarde.
status=0
restic cat config >/dev/null 2>&1 || status=$?
if [ "$status" -eq 10 ]; then
    log info "Dépôt absent, initialisation de $RESTIC_REPOSITORY"
    restic init --quiet
elif [ "$status" -ne 0 ]; then
    log error "Dépôt $RESTIC_REPOSITORY injoignable ou illisible (code restic $status)"
    exit 1
fi

# Une base en échec n'empêche pas de sauvegarder les autres
failed=""
for db in $databases; do
    # --stdin-from-command : restic lance pg_dump et refuse le snapshot si pg_dump échoue.
    # Format custom : compressé, et restaurable table par table avec pg_restore.
    if restic backup --quiet --host "$host" --tag "$db" --stdin-filename "$db.dump" \
        --stdin-from-command -- pg_dump --format=custom --dbname "$db"; then
        log info "Base $db sauvegardée"
    else
        log error "Échec de la sauvegarde de la base $db"
        failed="$failed $db"
    fi
done

# Conservation par base : 7 jours, 4 semaines, 6 mois. --prune libère la place.
# Le versioning du stockage Azure garde en plus les données supprimées 30 jours.
if restic forget --quiet --host "$host" --group-by host,tags \
    --keep-daily "${BACKUP_KEEP_DAILY:-7}" \
    --keep-weekly "${BACKUP_KEEP_WEEKLY:-4}" \
    --keep-monthly "${BACKUP_KEEP_MONTHLY:-6}" \
    --prune; then
    log info "Anciennes sauvegardes supprimées selon la politique de conservation"
else
    log error "Échec de la suppression des anciennes sauvegardes"
    failed="$failed forget"
fi

if [ -n "$failed" ]; then
    log error "Sauvegarde incomplète, en échec :$failed"
    exit 1
fi
log info "Sauvegarde terminée"
