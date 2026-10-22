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

### Base de données

Les scripts de `db/` (schémas, comptes des services, droits) ne sont exécutés par PostgreSQL qu'au premier démarrage, quand le volume est vide. Après une modification de ces scripts, ou si `api` et `etl` échouent avec `password authentication failed`, recréer la base (**supprime les données locales**) :

```bash
docker compose -f compose-local.yml down -v
```

Une fois la base déployée, toute modification des droits passe par un script de migration, pas par ces fichiers d'initialisation.

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

- Les services Python écrivent leurs logs en JSON avec `common/logs.py` (`configure_logging("nom-du-service")`) : Grafana peut alors filtrer par niveau.
- L'API expose ses métriques sur `/metrics`, hors de `/api` : Traefik ne les publie pas, seul Prometheus les lit.
- Le compte `monitoring` n'existe que dans une base créée après l'ajout de la supervision. Sur une base plus ancienne, PostgreSQL apparaît « injoignable » dans Grafana : recréer la base (voir **Base de données** ci-dessus).
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
| `security.yml` | vulnérabilité HIGH ou CRITICAL dans les fichiers, image Docker qui ne se construit pas ou qui contient une vulnérabilité corrigeable |
| `api-contract.yml` | réponse de l'API qui ne respecte pas son contrat OpenAPI (Schemathesis) |

La couverture porte sur la logique métier : `api/` et `common/` côté Python (`pyproject.toml`), `src/stores`, `src/lib` et `src/services` côté front (`front/vitest.config.ts`).

Pour la consulter sur GitHub, ouvrir le workflow `pre-commit` de la PR : le tableau de couverture (back et front) est sur la page **Summary**, et les rapports HTML détaillés, avec les lignes non couvertes, sont à télécharger dans **Artifacts** (`coverage`, gardé 14 jours). En local, le rapport du front est dans `front/coverage/index.html`.

Une vulnérabilité sans correctif disponible peut être acceptée **temporairement** dans `.trivyignore`, avec une justification et une date d'expiration (`exp:`).

## Règles de contribution

- `main` et `develop` sont protégées : aucun commit direct (bloqué par pre-commit).
- Une branche par ticket Jira : `feature/EV-12-description-courte`.
- Les messages de commit citent la clé Jira : `EV-12: ajoute l'import CSV`.
- Chaque pull request demande **2 relectures** avant le merge.
- Aucun secret dans le dépôt : utiliser `.env` (ignoré par Git).
