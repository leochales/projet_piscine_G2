# Déploiement sur la VM (runner GitHub auto-hébergé)

Un **runner GitHub auto-hébergé**, installé sur la VM, exécute le workflow [`deploy.yml`](../.github/workflows/deploy.yml). Il ouvre une connexion sortante vers GitHub : aucun port entrant ni clé SSH n'est nécessaire.

| Branche   | Environnement | Projet Docker     | URL                                                | Déclenchement                       |
|-----------|---------------|-------------------|----------------------------------------------------|-------------------------------------|
| `develop` | dev           | `enervision-dev`  | `https://<VM_IP>:8443` (`http://…:8080` redirige)  | manuel : Actions → Deploy → Run workflow |
| `main`    | prod          | `enervision-prod` | `https://<VM_IP>` (`http://…:80` redirige)         | push sur `main` (ou manuel)         |

Les deux environnements ont leurs propres conteneurs, volumes et base. Un **Traefik partagé** ([`infra/traefik/compose.yml`](traefik/compose.yml)) les sert en HTTPS, chacun sur son port, car la VM n'a pas de nom de domaine. Un lancement manuel sur une autre branche ne déploie rien (run *skipped*).

---

## Installation du runner

Une seule fois, depuis un compte administrateur de la VM. Prérequis : Docker avec le plugin `docker compose`, `curl` et `openssl`.

```bash
# 1. Utilisateur dédié, sans sudo, membre du groupe docker
sudo useradd -m -s /bin/bash github-runner
sudo usermod -aG docker github-runner

# 2. Téléchargement et enregistrement (version et token : GitHub → Settings → Actions
#    → Runners → New self-hosted runner, Linux x64 ; le token expire au bout d'une heure)
sudo su - github-runner
mkdir actions-runner && cd actions-runner
VERSION=2.xxx.x
curl -o runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${VERSION}/actions-runner-linux-x64-${VERSION}.tar.gz"
tar xzf runner.tar.gz && rm runner.tar.gz
./config.sh --url https://github.com/<owner>/<repo> --token <TOKEN> --name <nom-du-runner> --unattended
exit

# 3. Service systemd (compte administrateur)
cd /home/github-runner/actions-runner
sudo ./svc.sh install github-runner
sudo ./svc.sh start
```

Les labels par défaut (`self-hosted`, `Linux`, `X64`) correspondent à `runs-on: [self-hosted, linux]`. Le runner doit apparaître **Idle** dans **Settings → Actions → Runners**. Créer ensuite les secrets et variables ci-dessous.

---

## Secrets et variables

Le dépôt est privé sur un plan Free, sans *GitHub Environments*. Les secrets sont donc des secrets **du dépôt**, préfixés par environnement (**Settings → Secrets and variables → Actions**). Le workflow lit `DEV_X` ou `PROD_X` selon la branche et le transmet à `docker compose` sous le nom `X`. Aucun fichier `.env` n'est écrit sur la VM.

| Secrets (obligatoires)                               | Rôle                        |
|------------------------------------------------------|-----------------------------|
| `DEV_POSTGRES_PASSWORD` / `PROD_POSTGRES_PASSWORD`   | Superutilisateur PostgreSQL |
| `DEV_ETL_DB_PASSWORD` / `PROD_ETL_DB_PASSWORD`       | Compte `etl`                |
| `DEV_MODEL_DB_PASSWORD` / `PROD_MODEL_DB_PASSWORD`   | Compte `model`              |
| `DEV_API_DB_PASSWORD` / `PROD_API_DB_PASSWORD`       | Compte `api`                |
| `DEV_BACKUP_DB_PASSWORD` / `PROD_BACKUP_DB_PASSWORD` | Compte `backup`             |

| Variables                                    | Obligatoire | Rôle                                          |
|----------------------------------------------|-------------|-----------------------------------------------|
| `DEV_POSTGRES_USER` / `PROD_POSTGRES_USER`   | oui         | Nom du superutilisateur PostgreSQL            |
| `DEV_POSTGRES_DB` / `PROD_POSTGRES_DB`       | oui         | Nom de la base                                |
| `DEV_ETL_ENABLED` / `PROD_ETL_ENABLED`       | non         | `false` pour désactiver l'ETL (défaut `true`) |
| `VM_IP`                                      | oui         | IP de la VM, inscrite dans le certificat      |

Utiliser des mots de passe différents entre dev et prod. Ils ne sont appliqués qu'à la **création** de la base (volume vide) : modifier un secret ensuite ne change pas le mot de passe en base.

---

## Déroulement d'un déploiement

1. **Contrôles**, sur des runners GitHub : `pre-commit.yml` (lint, tests), `security.yml` (Trivy sur le code et les images), `api-contract.yml` (Schemathesis). Le déploiement ne démarre que s'ils réussissent tous.
2. **Certificat HTTPS** : auto-signé pour `VM_IP`, stocké dans `~/traefik-certs`, régénéré s'il expire sous 30 jours ou si `VM_IP` change.
3. **Traefik** : démarré s'il ne tourne pas. Il lit Docker via `docker-socket-proxy` (lecture seule, réseau interne), sans accès direct au socket.
4. **Application** : vérification des secrets, puis `docker compose -f compose-prod.yml build --pull` et `up -d --remove-orphans`.
5. **Santé** : `https://localhost:<port>/api/health` pendant 60 s. En cas d'échec, le job affiche l'état des conteneurs et les logs de l'API.
6. **Nettoyage** : images orphelines et cache de build de plus de 7 jours.

Un seul déploiement à la fois par environnement. Pour **revenir en arrière** : `git revert` sur la branche, puis redéployer (automatique sur `main`, **Run workflow** pour `develop`).

**Avertissement du navigateur** : le certificat est auto-signé. Pour le supprimer, importer `/home/github-runner/traefik-certs/cert.pem` comme autorité racine de confiance sur le poste (à refaire après chaque régénération).

---

## Exploitation

Commandes à lancer depuis un compte administrateur, dans `/home/github-runner/actions-runner` :

| Action                    | Commande                                         |
|---------------------------|--------------------------------------------------|
| État / démarrer / arrêter | `sudo ./svc.sh status` / `start` / `stop`        |
| Logs du service           | `sudo journalctl -u 'actions.runner.*' -f`       |
| Logs des jobs             | `_diag/Worker_*.log`                             |
| État des conteneurs       | `docker compose -p <traefik\|enervision-dev\|enervision-prod> ps` |

Le runner **se met à jour tout seul**. Pour le réenregistrer (runner supprimé côté GitHub, changement de nom) : `./svc.sh stop`, `./svc.sh uninstall`, `./config.sh remove --token <TOKEN>`, puis reprendre l'étape 2 de l'installation. Après un redémarrage de la VM, le service et les conteneurs repartent seuls.

---

## Limite connue : secrets et runner

Risque **accepté**, faute de plan payant :

- Un secret du dépôt est lisible par n'importe quel workflow, quelle que soit la branche. Les conditions `if:` de `deploy.yml` évitent un déploiement par erreur, mais ne protègent pas les secrets. Toute personne ayant les **droits d'écriture** peut lire `PROD_*`. Les PR venant de forks ne reçoivent aucun secret.
- Le runner exécute le code de toute branche dont un workflow cible `runs-on: self-hosted`. Comme `github-runner` est dans le groupe `docker`, les droits d'écriture donnent en pratique un accès root à la VM.

Mesures en place : droits d'écriture réservés à l'équipe, mots de passe différents entre dev et prod, un compte PostgreSQL par service.

Correctif si le dépôt passe sur GitHub Pro, Team, Enterprise ou en public : environnements `dev` (branche `develop`) et `prod` (branche `main`, approbation obligatoire), avec leurs propres secrets, et suppression de `ENV_PREFIX`.

---

## Dépannage

| Symptôme                                     | Cause probable                                  | Solution                                                         |
|----------------------------------------------|-------------------------------------------------|------------------------------------------------------------------|
| Job en *Queued* (« Waiting for a runner »)   | Runner *Offline* ou labels différents de `runs-on:` | `sudo ./svc.sh status`, vérifier les labels.                |
| `DEV_…` / `PROD_… manquant`                  | Secret ou variable absent                       | Le créer dans **Settings → Secrets and variables → Actions**.    |
| `permission denied … /var/run/docker.sock`   | `github-runner` hors du groupe `docker`         | `sudo usermod -aG docker github-runner`, puis redémarrer le service. |
| Ports 80/443/8080/8443 déjà utilisés         | Autre service sur la VM                         | Libérer le port, puis relancer le déploiement.                   |
| `password authentication failed` (api, etl)  | Secret modifié après la création de la base     | Mettre à jour le mot de passe en base, ou recréer le volume (**perte des données**). |
| Vérification de santé en échec               | API ou base qui ne démarre pas                  | Logs du job, puis `docker compose -p enervision-<env> logs api db`. |
| `no space left on device`                    | Images et cache de build accumulés              | `docker system prune -af` et `docker builder prune -af` (les volumes sont conservés). |
