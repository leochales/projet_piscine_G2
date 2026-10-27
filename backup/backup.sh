#!/bin/sh
# Sauvegarde nocturne (SMARTOPS-53) : dump de chaque base, envoyé chiffré dans le dépôt
# restic, puis oubli des sauvegardes trop anciennes.
#
#   backup.sh          chaque nuit : sauvegarde des bases, puis forget (sans prune)
#   backup.sh hebdo    le dimanche : la même chose, puis prune et restic check, à la
#                      suite dans le même processus pour ne jamais se disputer le verrou
#
# Variables lues :
#   RESTIC_REPOSITORY   dépôt restic (azure:restic-<env>:/ sur la VM)
#   RESTIC_PASSWORD     clé de chiffrement du dépôt : sans elle, les sauvegardes sont illisibles
#   AZURE_ACCOUNT_NAME, AZURE_ACCOUNT_SAS   accès au stockage Azure (dépôt azure: seulement)
#   PGHOST, PGUSER, PGPASSWORD              compte backup (lecture seule, db/06_roles.sql)
#   BACKUP_DATABASES    bases sauvegardées, dans l'ordre, obligatoire : la base de
#                       l'application (POSTGRES_DB, propre à chaque environnement) puis keycloak
#   DEPLOY_ENV          environnement (dev, prod, local ou ci), obligatoire, inscrit comme hôte
#
# Les deux bases ne sont pas figées au même instant : pg_dump ne sait pas prendre un
# instantané commun à deux bases. L'ordre limite l'effet d'un compte créé entre les deux
# dumps (quelques secondes, à 2 h) : enervision d'abord, keycloak ensuite. Une ligne de
# app.utilisateur a toujours son compte Keycloak dans la sauvegarde (le compte est créé
# avant la ligne) ; au pire, un compte Keycloak tout neuf n'a pas encore sa ligne, à
# recréer après une restauration. Aucun historique ne devient orphelin.
set -eu

mode="${1:-quotidien}"
databases="${BACKUP_DATABASES:-}"
env="${DEPLOY_ENV:-}"
host="enervision-$env"

# Même format JSON que common/logs.py, pour Loki et Grafana. Le message est nettoyé
# pour rester du JSON valide quelle que soit la sortie de restic : retours à la ligne et
# tabulations remplacés par des espaces, autres caractères de contrôle (codes couleur
# ANSI…) retirés, antislashs et guillemets échappés. Les secrets qu'un message d'erreur
# pourrait contenir sont masqués : signature de SAS, en clair (sig=…) ou encodée dans
# une URL (sig%3D…, jusqu'à la fin de l'adresse), et identifiants d'une adresse
# (https://utilisateur:mot-de-passe@…).
log() {
    message=$(printf '%s' "$2" | tr '\n\r\t' '   ' | tr -d '\000-\037\177' \
        | sed 's/sig=[^&" ]*/sig=***/g; s/sig%3[dD][^" ]*/sig%3D***/g; s#://[^/@ ]*@#://***@#g' \
        | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"timestamp":"%s","level":"%s","service":"backup","logger":"backup","message":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$message"
}

# Lance une commande restic. Sa sortie n'est affichée qu'en cas d'échec, dans un log
# d'erreur JSON (ses 20 dernières lignes). Code de retour : celui de la commande.
run() {
    status=0
    output=$("$@" 2>&1) || status=$?
    if [ "$status" -ne 0 ]; then
        log error "$(printf '%s' "$output" | tail -n 20)"
    fi
    return "$status"
}

# Un mode mal écrit (« hebdomadaire ») lancerait sinon une sauvegarde quotidienne sans
# prune ni restic check, sans aucune erreur
case "$mode" in
    quotidien | hebdo) ;;
    *)
        log error "Mode inconnu : $mode (quotidien ou hebdo)"
        exit 1
        ;;
esac

[ -n "$databases" ] || { log error "BACKUP_DATABASES manquant (base de l'application puis keycloak)"; exit 1; }
[ -n "${RESTIC_REPOSITORY:-}" ] || { log error "RESTIC_REPOSITORY manquant"; exit 1; }
[ -n "${RESTIC_PASSWORD:-}" ] || { log error "RESTIC_PASSWORD manquant"; exit 1; }
[ -n "${PGPASSWORD:-}" ] || { log error "PGPASSWORD manquant (mot de passe du compte backup)"; exit 1; }

# Sur la VM, chaque environnement écrit dans son propre conteneur Azure (dev ne peut pas
# écrire dans restic-prod, ni l'inverse) ; un dépôt local finirait dans le conteneur
# Docker, effacé au déploiement suivant. DEPLOY_ENV est obligatoire : sans lui, ce
# contrôle ne saurait pas quel dépôt attendre.
case "$env" in
    dev | prod)
        case "$RESTIC_REPOSITORY" in
            "azure:restic-$env:/"*) ;;
            *)
                log error "Dépôt restic refusé pour l'environnement $env : seul azure:restic-$env:/ est accepté"
                exit 1
                ;;
        esac
        ;;
    local | ci)
        # Hors de la VM, jamais dans les vrais dépôts : ni restic-prod, ni la racine de
        # restic-dev. Le premier lancement y créerait le dépôt avec le mot de passe local,
        # et toutes les sauvegardes de la VM échoueraient ensuite (« wrong password »).
        # Un sous-dossier personnel de restic-dev reste possible pour tester Azure.
        case "$RESTIC_REPOSITORY" in
            azure:restic-prod:* | azure:restic-dev | azure:restic-dev: | azure:restic-dev:/)
                log error "Dépôt restic refusé pour l'environnement $env : utiliser un sous-dossier, par exemple azure:restic-dev:/local-<nom>"
                exit 1
                ;;
        esac
        ;;
    "")
        log error "DEPLOY_ENV manquant (dev, prod, local ou ci)"
        exit 1
        ;;
    *)
        log error "DEPLOY_ENV inconnu : $env (dev, prod, local ou ci)"
        exit 1
        ;;
esac

# Attend jusqu'à 1 h un verrou tenu par une autre commande (sauvegarde lancée à la main)
lock="--retry-lock=1h"

# Premier lancement : le dépôt n'existe pas encore (code 10 de restic), on le crée.
# Toute autre erreur (réseau, SAS expiré, mauvais mot de passe) arrête la sauvegarde.
# L'adresse du dépôt n'est pas écrite dans les logs ; le message de restic l'est, pour
# distinguer la cause (SAS expiré, réseau, mauvais mot de passe).
status=0
output=$(restic cat config 2>&1 >/dev/null) || status=$?
if [ "$status" -eq 10 ]; then
    log info "Dépôt restic absent, initialisation"
    run restic init --quiet
elif [ "$status" -ne 0 ]; then
    log error "Dépôt restic injoignable ou illisible (code restic $status) : $(printf '%s' "$output" | tail -n 5)"
    exit 1
fi

failed=""
saved=0
for db in $databases; do
    # --stdin-from-command : restic lance pg_dump et refuse le snapshot si pg_dump échoue.
    # Format custom : compressé, et restaurable table par table avec pg_restore.
    if run restic backup --quiet "$lock" --host "$host" --tag "$db" \
        --stdin-filename "$db.dump" --stdin-from-command -- pg_dump --format=custom --dbname "$db"; then
        log info "Base $db sauvegardée"
        saved=$((saved + 1))
    else
        log error "Échec de la sauvegarde de la base $db"
        failed="$failed $db"
    fi
done

# Conservation par base : 7 jours, 4 semaines, 6 mois. Chaque nuit, forget retire
# seulement les snapshots en trop (quelques petits fichiers) ; la place n'est libérée
# que par le prune du dimanche, qui réécrit des données sur Azure. Sans aucune nouvelle
# sauvegarde, rien n'est oublié : on garde les dernières bonnes.
if [ "$saved" -gt 0 ]; then
    if run restic forget --quiet "$lock" --host "$host" --group-by host,tags \
        --keep-daily "${BACKUP_KEEP_DAILY:-7}" \
        --keep-weekly "${BACKUP_KEEP_WEEKLY:-4}" \
        --keep-monthly "${BACKUP_KEEP_MONTHLY:-6}"; then
        log info "Snapshots en trop oubliés selon la politique de conservation"
    else
        failed="$failed forget"
    fi
fi

if [ "$mode" = "hebdo" ]; then
    # Le versioning ou la suppression réversible du stockage Azure gardent en plus les
    # données supprimées par prune pendant 30 jours
    if run restic prune --quiet "$lock"; then
        log info "Place des snapshots oubliés libérée (prune)"
    else
        failed="$failed prune"
    fi
    # Relit 5 % des données (une partie différente à chaque fois) : détecte une
    # corruption sans tout télécharger. Un échec est une erreur, comme une sauvegarde ratée.
    if run restic check --quiet "$lock" --read-data-subset=5%; then
        log info "Dépôt vérifié (restic check, 5 % des données relues)"
    else
        log error "restic check a trouvé un problème dans le dépôt"
        failed="$failed check"
    fi
fi

if [ -n "$failed" ]; then
    log error "Sauvegarde incomplète, en échec :$failed"
    exit 1
fi
log info "Sauvegarde terminée"
