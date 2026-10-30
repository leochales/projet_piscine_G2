# EnerVision — Smart Energy Optimizer

Plateforme MVP d'optimisation énergétique : collecte des mesures de 7 sites, prédiction de consommation et tableau de bord.

## Structure

| Dossier   | Contenu | Documentation |
|-----------|---------|---------------|
| `api/`    | API métier (Python, FastAPI) : mesures, prévisions, alertes, recommandations, actions du dashboard | [`api/README.md`](api/README.md), Swagger sur `/api/docs` |
| `model/`  | Modèle de prévision (scikit-learn, MLflow) : jeu d'entraînement, entraînement, prévisions chaque heure, réentraînement chaque semaine. Ce sont des jobs planifiés, pas un service web : les prévisions sont écrites dans `gold.prediction` et servies par l'API | [`model/README.md`](model/README.md) |
| `etl/`    | Collecte des mesures de l'API Mock et transformation bronze → silver → gold (Python, Pydantic, fonctions SQL) | [`etl/README.md`](etl/README.md) |
| `common/` | Code Python partagé (configuration, accès base, logs) | |
| `front/`  | Tableau de bord (Vue 3) | [`front/README.md`](front/README.md) |
| `db/`     | Scripts SQL : schémas, comptes, fonctions de calcul de gold, tests SQL (`db/tests/`), scripts de démo (`db/demo/`) | section [Base de données](#base-de-données) |
| `backup/` | Sauvegarde nocturne chiffrée des bases (restic) | section [Sauvegarde](#sauvegarde-restic) |
| `infra/`  | Traefik, Keycloak, supervision, déploiement sur la VM, stockage Azure des sauvegardes (`infra/terraform/`) | [`infra/runner.md`](infra/runner.md), [`infra/terraform/README.md`](infra/terraform/README.md) |
| `data/`   | Historique CSV du sujet, versionné par DVC (seul `data/raw.dvc` est dans Git) | [`model/README.md`](model/README.md) |
| `.github/workflows/` | CI/CD (GitHub Actions) | section [CI](#ci-github-actions) |

## Livrables et documentation

| Livrable | Où le trouver |
|---|---|
| Pipelines CI/CD et intégration continue | `.github/workflows/`, sections [Hooks pre-commit](#hooks-pre-commit) et [CI](#ci-github-actions) ci-dessous, déroulé du déploiement dans [`infra/runner.md`](infra/runner.md) |
| Application déployée | VM de l'école, en dev et en prod : [`infra/runner.md`](infra/runner.md). Stockage des sauvegardes : [`infra/terraform/README.md`](infra/terraform/README.md) |
| Application d'analyse et interface | ETL : [`etl/README.md`](etl/README.md). API : [`api/README.md`](api/README.md). Dashboard : [`front/README.md`](front/README.md). Indicateurs métier : section [Supervision](#supervision-prometheus-grafana-loki) |
| Modèle, automatisation et pilotage | [`model/README.md`](model/README.md), section [Démo](#démo--simuler-un-pic-de-consommation) |

## Lancer le projet

Prérequis : Git, Docker et Docker Compose.

```bash
git clone <url-du-depot>
cd projet_piscine_G2
cp env.example .env      # PowerShell : Copy-Item env.example .env
docker compose -f compose-local.yml up -d --build
```

Tout passe par Traefik sur `http://localhost` : le dashboard, l'API (`/api`, Swagger sur `/api/docs`) et Keycloak (`/auth`, console d'administration sur `/auth/admin` avec `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`). Keycloak est à la même adresse que sur la VM : l'émetteur des jetons (`iss`) est donc le même pour le navigateur et pour l'API.

### Comptes de démonstration

Un compte par rôle, créés **automatiquement**, en local comme sur la VM :

| Compte | Rôles | Client | Sites |
|---|---|---|---|
| `admin@enervision.test` | GESTION-CLIENT, MONITORING | aucun (administrateur EnerVision : tous) | tous ; **pas créé en prod** |
| `gestion.client@demo.test` | GESTION-CLIENT | Démo EnerVision | tous ceux du client |
| `gestion.site@demo.test` | GESTION-SITE | Démo EnerVision | SITE002, SITE007 |
| `consult.client@demo.test` | CONSULT-CLIENT | Démo EnerVision | tous ceux du client |
| `consult.site@demo.test` | CONSULT-SITE | Démo EnerVision | SITE001 |
| `monitoring@enervision.test` | MONITORING | aucun | aucune donnée métier |

Mot de passe en local : `EnerVision-Demo-2026` (autre valeur : `SEED_PASSWORD` dans le `.env`, 12 caractères au moins).

Ils sont créés par l'API à chaque démarrage ([`api/seed.py`](api/seed.py)), avec les fonctions qui créeront aussi les vrais comptes ([`api/services/comptes.py`](api/services/comptes.py)) : compte créé dans Keycloak (client `enervision-admin`), enregistré dans `app.utilisateur`, puis ses sites dans `app.utilisateur_site`. Un compte déjà enregistré n'est jamais modifié : un mot de passe ou des rôles changés à la main sont gardés. Une création interrompue (compte dans Keycloak, sans rôles ou sans ligne en base) est reprise au démarrage suivant. Un compte mal décrit (client ou site inconnu) est ignoré, avec un avertissement dans les logs. Le seeding tourne en tâche de fond et attend Keycloak s'il n'est pas prêt ; le résultat est dans les logs de l'API (`docker compose -f compose-local.yml logs api | grep -i seed`).

Pour ajouter un compte : une ligne dans `COMPTES_DEMO` (`api/seed.py`), puis redémarrer l'API.

### Keycloak : page de connexion

Le realm `enervision` (`infra/keycloak/realm-enervision.json`) utilise le thème de connexion `enervision` ([`infra/keycloak/themes/enervision/login/`](infra/keycloak/themes/enervision/login/)), monté dans `/opt/keycloak/themes`. Il reprend le style du front (shadcn-vue) sans Tailwind : un thème FreeMarker qui hérite du thème `keycloak` de base, dont il remplace seulement :

- `template.ftl` : mise en page de toutes les pages (marque, carte, alerte) ;
- `login.ftl` : la page de connexion (courriel, mot de passe avec bouton œil). « Se souvenir de moi » et « Mot de passe oublié ? », désactivés dans le realm, n'y sont pas : à ajouter dans ce fichier s'ils sont activés ;
- `resources/css/enervision.css` : les composants Card, Label, Input, Button et Alert, avec les couleurs de `front/src/assets/main.css` (**à modifier aux deux endroits**) et la police Inter du front ;
- `messages/messages_fr.properties` : les textes propres à EnerVision ; les autres viennent de Keycloak (`msg(...)`). La page est en français seulement (`supportedLocales` du realm), sans choix de langue.

Le mode sombre suit le choix fait dans l'application (même clé `enervision-theme` du localStorage, Keycloak étant à la même adresse), sinon le réglage du système.

**Modifier le thème en local** : `compose-local.yml` lance Keycloak en `start-dev`, qui ne met pas les thèmes en cache : une modification est visible en rechargeant la page. Avec `start`, le cache se désactive par `--spi-theme-cache-themes=false` dans la commande du service ; sinon, redémarrer Keycloak (`docker compose -f compose-local.yml restart keycloak`). Un nouveau fichier ou un nouveau dossier de thème demande toujours un redémarrage.

**Base existante** : le realm n'est importé qu'au premier démarrage, quand il n'existe pas encore. Sur une base créée avant le thème, appliquer le thème et la langue une fois avec kcadm, avec le compte administrateur du `.env` (`KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, transmis au conteneur) :

```bash
docker compose -f compose-local.yml exec -T keycloak sh -c 'KC_CLI_PASSWORD="$KC_BOOTSTRAP_ADMIN_PASSWORD" /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080/auth --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --config /tmp/kcadm.config && /opt/keycloak/bin/kcadm.sh update realms/enervision -s loginTheme=enervision -s "supportedLocales=[\"fr\"]" --config /tmp/kcadm.config; rm -f /tmp/kcadm.config'
```

Sur la VM, `deploy.yml` le fait à chaque déploiement (étape « Configurer les realms Keycloak »). Keycloak y tourne en `start`, avec le cache des thèmes : le déploiement calcule une version du dossier du thème (label du conteneur), et un thème modifié recrée le conteneur `keycloak`. Le realm `master` (console d'administration) garde le thème par défaut.

### Base de données

Les scripts de `db/` (schémas, comptes des services, droits) sont exécutés par PostgreSQL au premier démarrage, quand le volume est vide. Sur une base existante, `db/tools/migrate.sh` les **rejoue tous**, dans l'ordre, sans toucher aux données. Le déploiement le lance à chaque fois. En local, le lancer après un `git pull` qui modifie `db/` ou `.env`, ou si un service échoue avec `password authentication failed`, si `keycloak` ne trouve pas sa base, ou si PostgreSQL apparaît « injoignable » dans Grafana :

```bash
docker compose -f compose-local.yml up -d db   # recrée db si .env a changé (nouveau mot de passe…)
docker compose -f compose-local.yml exec db bash /docker-entrypoint-initdb.d/tools/migrate.sh
```

Chaque script de `db/` doit donc pouvoir être **rejoué sans effet** sur une base à jour : `CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE VIEW`, `ON CONFLICT DO NOTHING`… La CI (`images.yml`) rejoue la migration sur sa base de test et échoue sinon. Règles :

- Ne jamais modifier une table dans le script qui l'a créée : un `CREATE TABLE IF NOT EXISTS` modifié ne change pas une table existante. Ajouter un nouveau script numéroté (`11_….sql`) avec `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`…
- Un seul script par numéro, exécutés dans l'ordre du nom.
- Les mots de passe des comptes sont réappliqués à chaque migration depuis les variables d'environnement.

Pour repartir d'une base vide (**supprime les données locales**) : `docker compose -f compose-local.yml down -v`.

Les sites à collecter sont déclarés dans `app.site` par l'application (`db/08_sites_demo.sql` pour les 7 sites de démo) : l'ETL ne fait que les lire. Comme les autres scripts, il est rejoué à chaque migration : un site de démo supprimé à la main réapparaît.

Les actions du dashboard (décisions sur les recommandations, prises en compte des alertes) sont enregistrées dans `app` par `db/10_actions.sql`, et non dans `gold`, que l'ETL et le modèle recalculent. Ce sont des historiques : l'API peut ajouter des lignes, mais ni les modifier ni les supprimer. Une alerte n'est prise en compte qu'une fois : la base refuse la deuxième. L'état courant se lit dans les vues `app.recommandation_etat` et `app.alerte_etat`.

Chaque minute, l'ETL crée les alertes dans `gold.alerte` (`source = 'etl'`, `db/17_gold_alertes.sql`, appelé par `etl/gold_alerts.py`) :

- **Pic de consommation** (`threshold`) : il commence après 3 mesures consécutives au seuil du site ou plus, et se termine après 3 mesures sous ce seuil. Il passe en `critical` si le maximum atteint vaut 110 % de la capacité ou plus, sinon il reste en `high`. Il n'a pas de message : le dashboard affiche la valeur atteinte et le seuil. Chaque site a son seuil, en % de sa capacité, dans `app.site.seuil_alerte_pct` : 100 % pour les datacenters, 98 % pour les usines et 90 % pour les autres sites au départ. Un nouveau site créé sans seuil reçoit celui de son type, et si son type est corrigé, son seuil suit, sauf s'il a été réglé à la main. Un seuil modifié n'est jamais écrasé par une migration.
- **Capteur en panne** (`sensor`, colonne `capteur`) : même règle des 3 minutes. Une panne du capteur de consommation est en `high`, une panne du capteur électrique en `medium`.

Une minute sans mesure (ou dont la mesure a été refusée) ne compte ni pour le début ni pour la fin d'une alerte, mais plus de 5 minutes sans mesure coupent la série : trois mesures espacées d'une heure n'ouvrent pas d'alerte. Relancer la détection met à jour l'alerte en cours au lieu d'en créer une nouvelle, même si son début change (seuil modifié, minute réécrite) : elle garde son identifiant, donc sa prise en compte.

Chaque heure, après ses prévisions, le modèle crée l'alerte **Pic de consommation prévu** (`predicted_peak`, `source = 'modele'`, `model/alerte_pic.py`) : un site dont le pic prévu atteint son seuil sur au moins une des 24 prochaines heures a une alerte en cours. Son début est la première heure prévue au-dessus du seuil, sa valeur le plus fort pic prévu (`valeur_le` : son heure), avec la même sévérité que les pics mesurés (`critical` dès 110 % de la capacité). Une seule alerte du modèle en cours par site (`db/19_alerte_modele.sql`) : les passages suivants la mettent à jour, et la terminent quand plus aucune heure n'est prévue au-dessus du seuil. Voir `model/README.md`.

Les tests SQL de `db/tests/` (droits des comptes, actions du dashboard) sont lancés par la CI (`images.yml`, sur la base de la stack de test). En local, sur une base qui tourne :

```bash
docker compose -f compose-local.yml exec -T db psql -v ON_ERROR_STOP=1 -U enervision -d enervision < db/tests/test_actions.sql
```

## Supervision (Prometheus, Grafana, Loki)

Démarrée avec le reste de la stack (`docker compose -f compose-local.yml up -d`), environ 1 Go de mémoire en plus.

Grafana : http://localhost/grafana (compte `admin`, mot de passe `GRAFANA_ADMIN_PASSWORD` du `.env`). Deux tableaux de bord sont chargés depuis le dépôt.

| Composant | Rôle | Configuration |
|---|---|---|
| Prometheus | collecte les métriques (Traefik, API, PostgreSQL), conservées 15 jours | `infra/monitoring/prometheus/` |
| postgres-exporter | statistiques de PostgreSQL et totaux du tableau métier, via le compte `monitoring` (rôle `pg_monitor`). Ce compte ne lit aucune mesure : seulement la vue d'agrégats `gold.supervision_metier` | `db/06_roles.sql`, `db/19_supervision_metier.sql`, `infra/monitoring/postgres-exporter/` |
| Alloy | lit les logs des conteneurs EnerVision et les envoie à Loki | `infra/monitoring/alloy/` |
| Loki | stocke les logs, conservés 7 jours | `infra/monitoring/loki/` |
| Grafana | tableaux de bord, chargés depuis le dépôt à chaque démarrage | `infra/monitoring/grafana/` |

### Tableau de bord EnerVision : socle

Il montre :

- les requêtes, erreurs 5xx et temps de réponse de chaque service routé par Traefik ;
- le détail par route de l'API ;
- l'état de PostgreSQL (connexion, taille, connexions) ;
- les logs de tous les conteneurs EnerVision, filtrables par service et par niveau.

### Tableau de bord EnerVision : métier

Il suit la collecte, les prévisions et les alertes, sans ouvrir la base. Les valeurs viennent de la vue `gold.supervision_metier` (`db/19_supervision_metier.sql`, testée par `db/tests/test_supervision_metier.sql`), lue par postgres-exporter avec la requête de `infra/monitoring/postgres-exporter/queries.yaml`. Chaque colonne devient une métrique Prometheus `enervision_*`.

| Panneau | Ce qu'il montre | Métrique |
|---|---|---|
| Mesures collectées | Mesures enregistrées dans bronze depuis 24 h, sites actifs | `enervision_mesures_collectees` |
| Dernière collecte | Heure du dernier enregistrement dans bronze. Une valeur qui vieillit veut dire que la collecte est arrêtée | `enervision_derniere_collecte_epoch` |
| Taux d'imputation | Part des minutes imputées sur les heures complètes des dernières 24 h. Orange dès 10 %, rouge dès 30 % | `enervision_taux_imputation_pct` |
| Puissance du parc | Somme des puissances des sites actifs dont la dernière mesure a moins de 5 minutes | `enervision_puissance_kw` |
| Prévisions écrites | Lignes de `gold.prediction` | `enervision_previsions_ecrites` |
| Dernier calcul | Heure de la dernière prévision. Elle doit avancer chaque heure | `enervision_dernier_calcul_epoch` |
| Écart prévu / réel | 100 × \|prévu − réel\| / réel sur les heures complètes des dernières 24 h. C'est l'erreur du modèle en production (voir [`model/README.md`](model/README.md), « Surveillance en production ») | `enervision_ecart_prevu_reel_pct` |
| Alertes en cours | Alertes ouvertes des sites actifs | `enervision_alertes_en_cours` |

Aucune règle d'alerte n'est configurée dans Prometheus ni dans Grafana : les tableaux de bord se lisent, ils ne préviennent pas. Les alertes de supervision (collecte arrêtée, disque, sauvegarde, dérive du modèle) sont l'objet de SMARTOPS-82.

### Logs et métriques

- L'API écrit ses logs en JSON avec `common/logs.py`. Chaque service Python doit appeler `configure_logging("nom-du-service")` au démarrage, plutôt que `logging.basicConfig` : sinon ses logs restent en texte et Grafana ne peut pas les filtrer par niveau.
- L'API expose ses métriques sur `/metrics`, hors de `/api` : Traefik ne les publie pas, seul Prometheus les lit.
- Le compte `monitoring` n'existe que dans une base créée ou migrée après l'ajout de la supervision. Si PostgreSQL apparaît « injoignable » dans Grafana, lancer la migration (voir **Base de données** ci-dessus).
- Un tableau de bord modifié dans Grafana n'est pas sauvegardé : exporter son JSON dans `infra/monitoring/grafana/dashboards/`.

## Sauvegarde (restic)

Chaque nuit à 2 h UTC, le conteneur `backup` ([`backup/`](backup/)) sauvegarde la base de l'application (celle de `POSTGRES_DB`, propre à chaque environnement) puis `keycloak`, dans la même exécution (les comptes de l'application sont liés à Keycloak). Chaque snapshot porte en tag le nom de sa base, et le fichier s'appelle `<base>.dump` :

- `pg_dump` (format custom) avec le compte `backup`, en lecture seule, envoyé directement à restic, sans fichier sur le disque ;
- chiffré par restic avec `RESTIC_PASSWORD` avant l'envoi : **sans cette clé, les sauvegardes sont illisibles**, la conserver aussi hors de GitHub ;
- sur la VM, dans le stockage Azure (`azure:restic-<env>:/`, voir `infra/terraform`) ; le script refuse tout autre dépôt en dev et en prod. En local, dans le volume `backup_home` ;
- conservation : 7 sauvegardes quotidiennes, 4 hebdomadaires et 6 mensuelles par base. Chaque nuit, `forget` oublie les snapshots en trop (rien si aucune base n'a été sauvegardée) ; le dimanche seulement, `prune` libère la place sur Azure puis `restic check` relit 5 % des données, à la suite dans le même job ;
- logs JSON au format commun ; un échec (base, `prune`, `check`) est un log `error` et le job se termine en erreur.

Les deux bases ne sont pas figées au même instant (`pg_dump` ne sait pas faire un instantané commun à deux bases). L'ordre fait qu'une ligne de `app.utilisateur` a toujours son compte Keycloak dans la sauvegarde : au pire, un compte créé pendant les quelques secondes entre les deux dumps n'a pas encore sa ligne, à recréer après une restauration.

En local, le service est dans le profil `backup`. Avec `RESTIC_PASSWORD` dans le `.env` :

```bash
docker compose -f compose-local.yml --profile backup run --rm backup /app/backup.sh
```

```bash
docker compose -f compose-local.yml --profile backup run --rm backup restic snapshots
```

Pour récupérer un dump (ici le dernier de la base `enervision`, le `POSTGRES_DB` du `.env` par défaut ; sur la VM, remplacer par le `POSTGRES_DB` de l'environnement) et l'inspecter avec `pg_restore` :

```bash
docker compose -f compose-local.yml --profile backup run --rm backup sh -c "restic dump latest enervision.dump --tag enervision | pg_restore --list"
```

La procédure de restauration complète est l'objet de SMARTOPS-54.

Le dépôt local est dans le volume `backup_home` (dossier `/home/backup/repo` du conteneur). Une première version de la branche utilisait un volume `backup_repo` : il n'est plus lu, et la sauvegarde suivante démarre un nouveau dépôt vide. Ce n'étaient que des sauvegardes de test locales ; pour les garder, copier le volume avant de le supprimer :

```bash
docker run --rm -v projet_piscine_g2_backup_repo:/ancien:ro -v projet_piscine_g2_backup_home:/home/backup alpine:3.23 sh -c "cp -a /ancien /home/backup/repo && chown -R 1000:1000 /home/backup/repo"
```

```bash
docker volume rm projet_piscine_g2_backup_repo
```

## Hooks pre-commit

Les vérifications (ruff, sqlfluff, hadolint, prettier, eslint, gitleaks…) tournent avant chaque commit ; les tests avec couverture (pytest, vitest), le typage (mypy, vue-tsc) et Trivy avant chaque push. Configuration : `.pre-commit-config.yaml`.

### Installation (une fois)

Depuis la racine du dépôt, avec Python 3.14 et Node 22 ou plus :

```bash
python3.14 -m venv .venv
.venv/bin/pip install pre-commit -r api/requirements-dev.txt   # Windows : .venv\Scripts\pip
npm --prefix front ci
.venv/bin/pre-commit install   # installe les hooks pre-commit et pre-push
```

Trivy doit aussi être installé sur la machine (`brew install trivy` sous macOS, voir la [documentation](https://trivy.dev/latest/getting-started/installation/) pour Windows et Linux).

### Après un `git pull`

Si `requirements*.txt` ou `front/package-lock.json` ont changé, réinstaller les dépendances, sinon les hooks du push échouent (par exemple `pytest-cov` ou `@vitest/coverage-v8` manquants, ou `pytest (model)` qui ne trouve pas scikit-learn) :

```bash
.venv/bin/pip install -r api/requirements-dev.txt -r model/requirements-dev.txt
npm --prefix front ci
```

### Bon à savoir

- Pas besoin d'activer le venv : les hooks Python passent par `infra/pre-commit/run_in_venv.py`, qui trouve le `.venv` tout seul (macOS, Linux et Windows).
- Pour lancer les vérifications à la main : `pre-commit run --all-files` (commit) et `pre-commit run --all-files --hook-stage pre-push` (push).
- Sous Windows, si `python` ouvre le Microsoft Store, rouvrir le terminal (ou l'IDE) après l'installation de Python.

## CI (GitHub Actions)

Chaque pull request vers `develop` ou `main` lance :

| Workflow | Ce qui bloque la PR |
|---|---|
| `pre-commit.yml` | lint et format (ruff, dont les règles de sécurité `S` de Bandit, eslint, prettier, sqlfluff, hadolint, gitleaks), tests et typage, **couverture sous 80 %** |
| `security.yml` | vulnérabilité HIGH ou CRITICAL dans les fichiers du dépôt, ou dans la configuration Terraform |
| `terraform.yml` | code Terraform mal formaté, invalide ou signalé par tflint (seulement si `infra/terraform/` change) |
| `images.yml` | image qui ne se construit pas ; stack de prod (Traefik, base, api, etl, front, backup) qui ne démarre pas ou échoue aux tests (dont une sauvegarde complète dans un dépôt restic local) ; redirection vers un autre hôte ou en HTTP, en-tête de sécurité ou CSP du front manquant, version exposée dans l'en-tête `Server`, script en ligne dans le front ; réponse de l'API qui ne respecte pas son contrat OpenAPI (Schemathesis, sur le conteneur) ; image qui contient une vulnérabilité corrigeable |

La couverture porte sur la logique métier : `api/` et `common/` côté Python (`pyproject.toml`), `src/stores`, `src/lib` et `src/services` côté front (`front/vitest.config.ts`).

Pour la consulter sur GitHub, ouvrir le workflow `pre-commit` de la PR : le tableau de couverture (back et front) est sur la page **Summary**, et les rapports HTML détaillés, avec les lignes non couvertes, sont à télécharger dans **Artifacts** (`coverage`, gardé 3 jours). En local, le rapport du front est dans `front/coverage/index.html`.

Une vulnérabilité sans correctif disponible peut être acceptée **temporairement** dans `.trivyignore`, avec une justification et une date d'expiration (`exp:`).

Les images tournent sans root : uid 1000 pour api, etl, model et backup, utilisateur `nginx` (uid 101) pour le front, qui écoute donc sur le port 8080 (règle Trivy DS-0002). Le scan de configuration de `security.yml` ne porte que sur `infra/terraform/` : les Dockerfile ne passent pas par ce scan.

### Déploiement et scan de l'application déployée

Le workflow `deploy.yml` relance les trois contrôles ci-dessus (`pre-commit.yml`, `security.yml`, `images.yml`), puis déploie sur la VM les images testées et publiées sur GHCR. Il se lance sur un push sur `main` (prod) ou à la main (dev, depuis `develop`). Le déroulé complet est dans [`infra/runner.md`](infra/runner.md).

Après un déploiement de dev, le job `zap` scanne l'application qui tourne avec OWASP ZAP (DAST) : scan passif du front, puis scan actif de l'API à partir de son contrat OpenAPI, avec un compte de démonstration en lecture seule. La prod n'est jamais scannée. Les alertes s'affichent dans le résumé du run (`infra/ci/zap_summary.py`). Une faille classée `FAIL` (injection SQL, XSS, traversée de chemin…) fait échouer le job `zap`, jamais le déploiement. Fonctionnement, rapports (artefact `zap-report`) et réglage des règles (`.zap/rules.tsv`) : [`infra/runner.md`](infra/runner.md#scan-zap-dev).

### Workflows lancés à la main

| Workflow | Rôle | Documentation |
|---|---|---|
| `deploy.yml` (Deploy) | Déployer `develop` sur dev. `main` est déployé en prod à chaque push | [`infra/runner.md`](infra/runner.md) |
| `dataset.yml` (Dataset) | Construire le jeu d'entraînement sur la VM, puis entraîner et enregistrer le modèle dans MLflow | [`model/README.md`](model/README.md) |
| `demo.yml` (Démo) | Simuler un pic de consommation sur dev | section [Démo](#démo--simuler-un-pic-de-consommation) |
| `azure-storage-check.yml` (Azure storage check) | Vérifier que la VM peut écrire dans le stockage Azure des sauvegardes | [`infra/terraform/README.md`](infra/terraform/README.md) |

Aucun de ces workflows ne se déclenche sur une pull request : ils tournent sur le runner de la VM, et le dépôt est public (voir [`infra/runner.md`](infra/runner.md), « Limite connue »).

## Démo : simuler un pic de consommation

L'API Mock ne produit pas de pic à la demande. Pour montrer la chaîne complète (mesure, alerte, recommandation, prise en compte), les scripts de `db/demo/` font monter les mesures d'un site au-dessus de son seuil. Ils tournent sur dev seulement, avec le workflow **Démo** (Actions → Démo → Run workflow, branche `develop`).

| Action | Script | Effet |
|---|---|---|
| `pic` | `db/demo/pic.sql` | Pendant `minutes` minutes (5 à 180), chaque mesure collectée du `site` choisi arrive en bronze à `charge` fois sa capacité (1.15 = 115 %). Un trigger temporaire remplace la consommation au moment où la mesure arrive : la collecte continue normalement |
| `reset` | `db/demo/reset.sql` | Retire les prises en compte et les décisions des alertes en cours, sans arrêter le pic, pour refaire la démonstration |
| `fin_pic` | `db/demo/fin_pic.sql` | Arrête le pic et retire le trigger |

L'ETL fait le reste, sans code propre à la démo : silver, gold, l'alerte de dépassement après 3 minutes au-dessus du seuil, puis sa recommandation. L'alerte apparaît 4 à 5 minutes après le lancement et se ferme 3 minutes après la fin du pic. Lancer `pic` 5 minutes avant de montrer le dashboard.

## Règles de contribution

Le travail est suivi dans Jira (projet `SMARTOPS`). Un ticket est terminé quand il respecte la [Definition of Done](https://enervisionproject.atlassian.net/wiki/spaces/ENERVISION/pages/1998851).

- `main` et `develop` sont protégées. Aucun commit direct : le hook `no-commit-to-branch` le bloque.
- Une branche par ticket, créée depuis `develop` à jour. Son nom est celui que propose Jira : `EADL_2025_RENNES_G2/<numéro>-<titre-du-ticket>`, par exemple `EADL_2025_RENNES_G2/38-endpoints-mesures-et-consommation`.
- Chaque message de commit commence par la clé du ticket : `SMARTOPS-38: contrôle la période de consommation`.
- Une pull request par ticket, vers `develop`. Elle est fusionnée quand elle est relue et approuvée par **1 personne** et que la CI passe.
- La documentation change dans la même pull request que le code : README du service, Swagger, et page Confluence si besoin.
- Un script de `db/` doit pouvoir être rejoué (voir [Base de données](#base-de-données)).
- `main` reçoit `develop` par une pull request, ce qui déploie la prod.
- Aucun secret dans le dépôt : utiliser `.env` (ignoré par Git) en local, et les secrets GitHub pour la VM.
