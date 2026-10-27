# EnerVision — Smart Energy Optimizer

Plateforme MVP d'optimisation énergétique : collecte des mesures de 7 sites, prédiction de consommation et tableau de bord.

## Structure

| Dossier   | Contenu                                         |
|-----------|-------------------------------------------------|
| `api/`    | API métier (Python, FastAPI)                    |
| `model/`  | Service de prédiction (FastAPI, scikit-learn, MLflow) |
| `etl/`    | Chargement et nettoyage des données (pandas)    |
| `common/` | Code Python partagé (schémas, accès base, config) |
| `front/`  | Tableau de bord (Vue 3)                         |
| `db/`     | Scripts SQL d'initialisation                    |
| `infra/`  | Docker, CI, déploiement                         |

## Lancer le projet

Prérequis : Git, Docker et Docker Compose.

```bash
git clone <url-du-depot>
cd projet_piscine_G2
cp .env.example .env      # PowerShell : Copy-Item .env.example .env
docker compose up --build
```

Tout passe par Traefik sur `http://localhost` : le dashboard, l'API (`/api`, Swagger sur `/api/docs`) et Keycloak (`/auth`, console d'administration sur `/auth/admin` avec `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`). Keycloak est à la même adresse que sur la VM : l'émetteur des jetons (`iss`) est donc le même pour le navigateur et pour l'API.

### Comptes de démonstration

Un compte par rôle, listé dans [`infra/seed/utilisateurs.csv`](infra/seed/utilisateurs.csv) : créé dans Keycloak et enregistré dans `app.utilisateur` (sinon l'API répond 403). Tous ont le même mot de passe, `EnerVision-Demo-2026` (`SEED_PASSWORD=...` pour en choisir un autre, 12 caractères au moins). La stack démarrée :

```bash
infra/seed/utilisateurs.sh local
```

Rejouable : un compte existant reçoit le mot de passe, les rôles et le client du fichier. Même commande avec `dev` sur la VM ; refusé en prod.

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

Les tests SQL de `db/tests/` (droits des comptes, actions du dashboard) sont lancés par la CI (`images.yml`, sur la base de la stack de test). En local, sur une base qui tourne :

```bash
docker compose -f compose-local.yml exec -T db psql -v ON_ERROR_STOP=1 -U enervision -d enervision < db/tests/test_actions.sql
```

## Supervision (Prometheus, Grafana, Loki)

Non démarrée par défaut (environ 1 Go de mémoire) : elle est dans le profil Compose `monitoring`.

```bash
docker compose -f compose-local.yml --profile monitoring up -d
```

Grafana : http://localhost/grafana (compte `admin`, mot de passe `GRAFANA_ADMIN_PASSWORD` du `.env`). Le tableau de bord **EnerVision : socle** montre :

- les requêtes, erreurs 5xx et temps de réponse de chaque service routé par Traefik ;
- le détail par route de l'API ;
- l'état de PostgreSQL (connexion, taille, connexions) ;
- les logs de tous les conteneurs EnerVision, filtrables par service et par niveau.

| Composant | Rôle | Configuration |
|---|---|---|
| Prometheus | collecte les métriques (Traefik, API, PostgreSQL), conservées 15 jours | `infra/monitoring/prometheus/` |
| postgres-exporter | statistiques de PostgreSQL, via le compte `monitoring` (rôle `pg_monitor`, aucune donnée métier) | `db/06_roles.sql` |
| Alloy | lit les logs des conteneurs EnerVision et les envoie à Loki | `infra/monitoring/alloy/` |
| Loki | stocke les logs, conservés 7 jours | `infra/monitoring/loki/` |
| Grafana | tableaux de bord, chargés depuis le dépôt à chaque démarrage | `infra/monitoring/grafana/` |

- L'API écrit ses logs en JSON avec `common/logs.py`. Chaque service Python doit appeler `configure_logging("nom-du-service")` au démarrage, plutôt que `logging.basicConfig` : sinon ses logs restent en texte et Grafana ne peut pas les filtrer par niveau.
- L'API expose ses métriques sur `/metrics`, hors de `/api` : Traefik ne les publie pas, seul Prometheus les lit.
- Le compte `monitoring` n'existe que dans une base créée ou migrée après l'ajout de la supervision. Si PostgreSQL apparaît « injoignable » dans Grafana, lancer la migration (voir **Base de données** ci-dessus).
- Un tableau de bord modifié dans Grafana n'est pas sauvegardé : exporter son JSON dans `infra/monitoring/grafana/dashboards/`.

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

Si `requirements*.txt` ou `front/package-lock.json` ont changé, réinstaller les dépendances, sinon les hooks du push échouent (par exemple `pytest-cov` ou `@vitest/coverage-v8` manquants) :

```bash
.venv/bin/pip install -r api/requirements-dev.txt
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
| `security.yml` | vulnérabilité HIGH ou CRITICAL dans les fichiers du dépôt |
| `images.yml` | image qui ne se construit pas ; stack de prod (Traefik, base, api, etl, front) qui ne démarre pas ou échoue aux tests ; réponse de l'API qui ne respecte pas son contrat OpenAPI (Schemathesis, sur le conteneur) ; image qui contient une vulnérabilité corrigeable |

La couverture porte sur la logique métier : `api/` et `common/` côté Python (`pyproject.toml`), `src/stores`, `src/lib` et `src/services` côté front (`front/vitest.config.ts`).

Pour la consulter sur GitHub, ouvrir le workflow `pre-commit` de la PR : le tableau de couverture (back et front) est sur la page **Summary**, et les rapports HTML détaillés, avec les lignes non couvertes, sont à télécharger dans **Artifacts** (`coverage`, gardé 3 jours). En local, le rapport du front est dans `front/coverage/index.html`.

Une vulnérabilité sans correctif disponible peut être acceptée **temporairement** dans `.trivyignore`, avec une justification et une date d'expiration (`exp:`).

## Règles de contribution

- `main` et `develop` sont protégées : aucun commit direct (bloqué par pre-commit).
- Une branche par ticket Jira : `feature/EV-12-description-courte`.
- Les messages de commit citent la clé Jira : `EV-12: ajoute l'import CSV`.
- Chaque pull request demande **2 relectures** avant le merge.
- Aucun secret dans le dépôt : utiliser `.env` (ignoré par Git).
