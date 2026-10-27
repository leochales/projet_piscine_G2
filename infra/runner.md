# Déploiement sur la VM (runner GitHub auto-hébergé)

Un **runner GitHub auto-hébergé**, installé sur la VM, exécute le workflow [`deploy.yml`](../.github/workflows/deploy.yml). Il ouvre une connexion sortante vers GitHub : aucun port entrant ni clé SSH n'est nécessaire.

| Branche   | Environnement | Projet Docker     | URL                                                | Déclenchement                       |
|-----------|---------------|-------------------|----------------------------------------------------|-------------------------------------|
| `develop` | dev           | `enervision-dev`  | `https://<VM_IP>:8443` (`http://…:8080` redirige)  | manuel : Actions → Deploy → Run workflow |
| `main`    | prod          | `enervision-prod` | `https://<VM_IP>` (`http://…:80` redirige)         | push sur `main` (ou manuel)         |

Les deux environnements ont leurs propres conteneurs, volumes et base. Un **Traefik partagé** ([`infra/traefik/compose.yml`](traefik/compose.yml)) les sert en HTTPS, chacun sur son port, car la VM n'a pas de nom de domaine. Un lancement manuel sur une autre branche ne déploie rien (run *skipped*).

Keycloak est servi à la même adresse, sous `/auth` (`https://<VM_IP>/auth`, `https://<VM_IP>:8443/auth`). La console d'administration est sur `https://<VM_IP>/auth/admin` (prod) et `https://<VM_IP>:8443/auth/admin` (dev), avec l'administrateur du realm `master` (`<ENV>_KEYCLOAK_ADMIN`). Chaque déploiement active la protection contre les essais de mots de passe sur ce realm : 5 échecs bloquent le compte 15 minutes, puis plus longtemps, jusqu'à 1 heure. `kcadm.sh` reste utilisable dans le conteneur (voir [Faire évoluer le realm Keycloak](#faire-évoluer-le-realm-keycloak)).

---

## Installation du runner

Une seule fois, depuis un compte administrateur de la VM. Prérequis : Docker avec le plugin `docker compose`, `curl`, `openssl`, `python3` et `acl` (données du jeu d'entraînement).

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
| `DEV_KEYCLOAK_DB_PASSWORD` / `PROD_KEYCLOAK_DB_PASSWORD` | Compte `keycloak` (base `keycloak`) |
| `DEV_KEYCLOAK_ADMIN_PASSWORD` / `PROD_KEYCLOAK_ADMIN_PASSWORD` | Administrateur initial de Keycloak |
| `DEV_KEYCLOAK_ADMIN_CLIENT_SECRET` / `PROD_KEYCLOAK_ADMIN_CLIENT_SECRET` | Secret du client `enervision-admin` (création des comptes par l'API) |

| Variables                                    | Obligatoire | Rôle                                          |
|----------------------------------------------|-------------|-----------------------------------------------|
| `DEV_POSTGRES_USER` / `PROD_POSTGRES_USER`   | oui         | Nom du superutilisateur PostgreSQL            |
| `DEV_POSTGRES_DB` / `PROD_POSTGRES_DB`       | oui         | Nom de la base                                |
| `DEV_ETL_ENABLED` / `PROD_ETL_ENABLED`       | non         | `false` pour désactiver l'ETL (défaut `true`) |
| `DEV_KEYCLOAK_ADMIN` / `PROD_KEYCLOAK_ADMIN` | oui         | Identifiant de l'administrateur initial de Keycloak |
| `VM_IP`                                      | oui         | IP de la VM, inscrite dans le certificat et dans l'adresse de retour de connexion de Keycloak (`FRONT_URL`) |
| `DVC_STORE`                                  | non         | Dossier du stockage DVC sur la VM (défaut `/srv/enervision-dvc`) |

Utiliser des mots de passe différents entre dev et prod. Les mots de passe des comptes des services (`ETL_`, `MODEL_`, `API_`, `BACKUP_`, `KEYCLOAK_DB_PASSWORD`) sont **réappliqués à chaque déploiement** par la migration de la base : pour en changer un, modifier le secret puis redéployer. Exceptions :
- `POSTGRES_PASSWORD` (superutilisateur) n'est appliqué qu'à la **création** de la base (volume vide). Le changer ensuite : `ALTER ROLE` dans la base, puis mettre à jour le secret ;
- `KEYCLOAK_ADMIN` et `KEYCLOAK_ADMIN_PASSWORD` ne servent qu'au premier démarrage de Keycloak, pour créer l'administrateur du realm `master`. Le modifier ensuite se fait dans la console de Keycloak ;
- `KEYCLOAK_ADMIN_CLIENT_SECRET` n'est lu qu'à l'import du realm : le changer demande aussi une action dans Keycloak (voir [Faire évoluer le realm Keycloak](#faire-évoluer-le-realm-keycloak)).

---

## Déroulement d'un déploiement

1. **Contrôles**, en parallèle sur des runners GitHub : `pre-commit.yml` (lint, tests), `security.yml` (Trivy sur le code) et `images.yml`. Ce dernier construit api, etl, front et model **une seule fois**, démarre la stack de prod complète avec ces images (Traefik, scripts `db/`, comptes PostgreSQL, ETL, front), rejoue la migration de la base, lance le job du jeu d'entraînement sur un petit CSV, les tests SQL et Schemathesis sur le conteneur de l'API, scanne les images avec Trivy, puis les publie sur GHCR (`ghcr.io/<owner>/enervision-<service>:<sha du commit>`). Le déploiement ne démarre que si tout réussit.
2. **Certificat HTTPS** : auto-signé pour `VM_IP`, stocké dans `~/traefik-certs`, régénéré s'il expire sous 30 jours ou si `VM_IP` change.
3. **Traefik** : démarré s'il ne tourne pas. Il lit Docker via `docker-socket-proxy` (lecture seule, réseau interne), sans accès direct au socket.
4. **Vérifier les secrets** : toutes les variables et tous les secrets obligatoires, avant de toucher à la VM. Le job liste ceux qui manquent et s'arrête.
5. **Récupérer les images** : `docker compose pull` des images du commit (connexion à GHCR avec le `GITHUB_TOKEN` du job, retirée juste après). La VM ne reconstruit rien : elle démarre exactement les images testées et scannées.
6. **Migrer la base** : démarrage de Postgres, attente qu'il réponde (120 s au plus, sinon le déploiement s'arrête avec les logs de `db`), puis `db/tools/migrate.sh`, qui rejoue tous les scripts de `db/` sur la base existante : nouvelles tables, comptes, droits et mots de passe. Les scripts doivent pouvoir être rejoués sans effet (voir la section **Base de données** du README). Si un script échoue, les nouveaux conteneurs ne sont pas démarrés : l'ancienne version continue de tourner, sur une base **partiellement migrée** (les scripts précédents restent appliqués, chaque script annulant seulement ses propres changements). Le risque est faible tant que les scripts ne font qu'ajouter (tables, colonnes, droits) : l'ancienne version les ignore. Corriger le script et redéployer : la migration reprend depuis le début.
7. **Déployer** : `up -d --no-build --remove-orphans`.
8. **Santé** : `https://localhost:<port>/api/health` pendant 60 s. En cas d'échec, le job affiche l'état des conteneurs et les logs de l'API.
9. **Nettoyage** : images orphelines et anciennes versions de nos images qu'aucun conteneur n'utilise. Sur GHCR, seules les 20 dernières versions de chaque image sont conservées.

Un seul déploiement à la fois par environnement. Pour **revenir en arrière** : rouvrir le run **Deploy** d'un commit précédent et relancer **uniquement le job Deploy** (icône ↻ du job). Les images de ce commit sont reprises sur GHCR telles quelles. Relancer tout le run reconstruirait les images. Au-delà des 20 dernières versions, faire un `git revert` sur la branche et redéployer.

**Avertissement du navigateur** : le certificat est auto-signé. Pour le supprimer, importer `/home/github-runner/traefik-certs/cert.pem` comme autorité racine de confiance sur le poste (à refaire après chaque régénération).

---

## Jeu d'entraînement du modèle

Le jeu est construit à partir de l'historique CSV du sujet (`model/README.md`). Les fichiers (13 Mo) ne sont pas dans Git : ils sont versionnés par [DVC](https://dvc.org/). Git garde seulement `data/raw.dvc` (empreinte du dossier `data/raw`), les fichiers sont dans un stockage DVC sur la VM, dans `/srv/enervision-dvc`. Le remote `vm` du dépôt y accède en SSH.

**Créer le stockage** (une fois, depuis un compte administrateur de la VM). Le groupe `enervision-dvc` réunit les comptes des développeurs, qui envoient les données en SSH, et `github-runner`, qui les lit :

```bash
sudo groupadd enervision-dvc
sudo usermod -aG enervision-dvc github-runner
sudo usermod -aG enervision-dvc <compte-admin>      # un par développeur
sudo mkdir -p /srv/enervision-dvc
sudo chgrp enervision-dvc /srv/enervision-dvc
sudo chmod 2775 /srv/enervision-dvc                 # les sous-dossiers héritent du groupe
sudo setfacl -d -m g::rwx /srv/enervision-dvc       # et restent modifiables par le groupe
```

**Sur un poste de développeur** : `pip install "dvc[ssh]==3.67.1"` dans le venv, puis déclarer l'alias SSH `enervision-vm` utilisé par le remote, dans `~/.ssh/config` :

```
Host enervision-vm
    HostName <VM_IP>
    User <compte-admin>
```

**Envoyer les données** (une fois, puis à chaque nouvelle version), depuis la racine du dépôt, avec les fichiers du sujet dans `data/raw/` :

```bash
dvc push
```

Pour une nouvelle version : modifier `data/raw/`, `dvc add data/raw`, commiter `data/raw.dvc` dans une PR, puis `dvc push`. Sans `dvc push`, le commit pointe vers des données que la VM n'a pas.

**Sur la VM**, DVC n'est pas installé : `infra/dataset/pull.py` (bibliothèque standard de `python3`) lit le stockage directement sur le disque, dans le format de DVC. Chaque déploiement lance `pull.py --check`, qui vérifie sans rien copier que le stockage a la version de `data/raw.dvc` ; si elle manque, le déploiement continue avec un avertissement. Le workflow **Dataset** lance `pull.py`, qui copie cette version dans `data/raw` en vérifiant l'empreinte MD5 de chaque fichier, puis la monte en lecture seule dans le conteneur du jeu.

**Construire le jeu** : Actions → **Dataset** → Run workflow, sur `develop` (dev) ou `main` (prod). Le workflow lance l'image `enervision-model` de la version déployée (même commit que l'API en service), avec le code et `data/raw.dvc` de ce commit. Le déploiement télécharge cette image et crée le conteneur du job sans le démarrer, pour que le nettoyage des images la garde : lancer d'abord **Deploy** si l'environnement n'est pas déployé. Le jeu et son rapport sont enregistrés dans le MLflow de l'environnement (expérience `jeu-entrainement`) et gardés dans le volume `dataset_data`.

**MLflow** tourne dans chaque environnement sur un réseau interne, sans route Traefik : son interface n'a pas d'authentification. Pour la consulter, ouvrir un tunnel SSH vers le conteneur :

```bash
ssh -L 5000:<ip-du-conteneur-mlflow>:5000 <admin>@<VM_IP>
```

L'IP du conteneur s'obtient sur la VM avec `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' enervision-prod-mlflow-1`, puis l'interface est sur http://localhost:5000/mlflow.

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

## Faire évoluer le realm Keycloak

Keycloak démarre avec `--import-realm` : il importe [`infra/keycloak/realm-enervision.json`](keycloak/realm-enervision.json) **seulement si le realm `enervision` n'existe pas encore**, c'est-à-dire au premier déploiement d'un environnement. Ensuite, le realm vit dans la base `keycloak` et les déploiements suivants ignorent le fichier.

Conséquence : une modification du JSON (rôle, redirect URI, politique de mot de passe, client…) n'atteint **pas** les environnements déjà déployés. Pour faire évoluer le realm :

1. Modifier le JSON et le commiter : il reste la référence pour le local et les futurs environnements.
2. Reporter le même changement sur dev, vérifier, puis sur prod, dans la console d'administration ou avec `kcadm.sh` dans le conteneur.

Ne pas supprimer le realm pour forcer un nouvel import : les comptes des utilisateurs seraient perdus.

```bash
# Se connecter (une fois par session ; demande le mot de passe KEYCLOAK_ADMIN_PASSWORD de l'environnement)
docker compose -p enervision-<env> exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080/auth --realm master --user <KEYCLOAK_ADMIN>

# Raccourci pour les commandes suivantes
kcadm() { docker compose -p enervision-<env> exec keycloak /opt/keycloak/bin/kcadm.sh "$@"; }

# Ajouter un rôle du realm
kcadm create roles -r enervision -s name=NOUVEAU-ROLE -s 'description=…'

# Identifiant interne d'un client (nécessaire pour le modifier)
kcadm get clients -r enervision -q clientId=enervision-front --fields id

# Remplacer les redirect URIs du front
kcadm update clients/<id> -r enervision -s 'redirectUris=["https://<VM_IP>/*"]'
```

### Créer un compte (premier administrateur, comptes de test)

Les comptes se créent dans Keycloak. En temps normal, ce sont les gestionnaires qui les créent depuis le dashboard (`POST /api/utilisateurs`, SMARTOPS-84). À la main, on passe par l'administration de Keycloak : la console (`http://localhost/auth/admin` en local, `https://<VM_IP>[:8443]/auth/admin` sur la VM) ou `kcadm.sh`.

**Comptes de démonstration sur dev** : `infra/seed/utilisateurs.sh` fait les deux étapes ci-dessous pour chaque ligne de `infra/seed/utilisateurs.csv` (un compte par rôle), avec l'administrateur initial de Keycloak. Depuis la racine du dépôt sur la VM, avec un compte du groupe `docker` :

```bash
infra/seed/utilisateurs.sh dev
```

Mot de passe de tous les comptes : `EnerVision-Demo-2026`, ou `SEED_PASSWORD` s'il est défini. Le script refuse la prod. Il échoue si le mot de passe de l'administrateur `master` a été changé depuis le premier démarrage de Keycloak.

**Attention** : l'API n'accepte que les utilisateurs enregistrés dans `app.utilisateur`, car c'est là qu'elle trouve leur entreprise. Un compte créé dans Keycloak sans cette ligne reçoit un 403.

1. Créer le compte dans Keycloak et noter son identifiant (`sub` des jetons). Avec le raccourci `kcadm` ci-dessus :

    ```bash
    kcadm create users -r enervision -i -s username=<email> -s email=<email> \
      -s firstName=<prénom> -s lastName=<nom> -s enabled=true
    # Mot de passe provisoire : demandé sans être affiché, à changer à la première connexion
    kcadm set-password -r enervision --username <email> --temporary
    kcadm add-roles -r enervision --uusername <email> --rolename <CONSULT-SITE|CONSULT-CLIENT|GESTION-SITE|GESTION-CLIENT>
    ```

    Dans la console : realm `enervision`, *Users* → *Create user*, onglet *Credentials* (mot de passe, *Temporary* sur On), onglet *Role mapping*. L'identifiant est affiché en haut de la fiche de l'utilisateur.

2. Enregistrer le compte dans `app.utilisateur`, avec le même identifiant :

    ```bash
    docker compose -p enervision-<env> exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    ```

    ```sql
    -- Compte rattaché à un client. INTO STRICT : erreur si le nom du client est mal
    -- écrit, au lieu d'un INSERT 0 0 silencieux (le compte recevrait alors un 403)
    DO $$
    DECLARE
        client BIGINT;
    BEGIN
        SELECT id_client INTO STRICT client FROM app.client WHERE nom = 'Démo EnerVision';
        INSERT INTO app.utilisateur (id, id_client) VALUES ('<sub>', client);
    END
    $$;

    -- Administrateur EnerVision (aucun client)
    INSERT INTO app.utilisateur (id) VALUES ('<sub>');
    ```

    Noms des clients existants : `SELECT nom FROM app.client;`

    En local : `docker compose -f compose-local.yml exec db ...`, ou pgAdmin.

### Changer le secret de `enervision-admin`

Le secret est injecté dans le realm à l'import : modifier `<ENV>_KEYCLOAK_ADMIN_CLIENT_SECRET` dans GitHub ne suffit pas.

1. Générer un nouveau secret dans Keycloak : `kcadm create clients/<id>/client-secret -r enervision`, puis le lire avec `kcadm get clients/<id>/client-secret -r enervision`.
2. Le copier dans le secret GitHub `DEV_KEYCLOAK_ADMIN_CLIENT_SECRET` ou `PROD_KEYCLOAK_ADMIN_CLIENT_SECRET`.
3. Redéployer, pour que l'API reçoive le nouveau secret. Entre l'étape 1 et la fin du déploiement, la création de comptes par l'API échoue.

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
| `password authentication failed` (api, etl)  | Base non migrée depuis le changement du secret  | Redéployer : l'étape « Migrer la base » réapplique les mots de passe. |
| Étape « Migrer la base » en échec            | Script de `db/` qui ne peut pas être rejoué, ou erreur SQL | Log de l'étape (le script fautif est le dernier `== …` affiché). L'ancienne version tourne toujours : corriger le script et redéployer. |
| Vérification de santé en échec               | API ou base qui ne démarre pas                  | Logs du job, puis `docker compose -p enervision-<env> logs api db`. |
| `pull access denied` / `manifest unknown` (ghcr.io) | Image absente de GHCR (job `images` en échec, ou version purgée) | Vérifier le job `images` du run ; au-delà de 20 versions, redéployer un commit récent. |
| `no space left on device`                    | Images accumulées                               | `docker system prune -af` (les volumes sont conservés). |
