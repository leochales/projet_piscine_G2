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

## Hooks pre-commit

Les vérifications (ruff, sqlfluff, hadolint, prettier, eslint…) tournent avant chaque commit ; les tests (pytest, vitest, vue-tsc, mypy) avant chaque push. Configuration : `.pre-commit-config.yaml`.

```bash
pip install pre-commit
pre-commit install        # installe les hooks pre-commit et pre-push
pre-commit run --all-files
```

Les hooks locaux appellent `python -m pytest`, `python -m mypy` et les scripts npm du front (`lint`, `format`, `type-check`, `test:unit` dans `front/package.json`) : pas de bash, ça fonctionne aussi sous Windows. Activer le venv du projet (avec pytest et mypy) avant de pousser. Sous Windows, si `python` ouvre le Microsoft Store, rouvrir le terminal (ou l'IDE) après l'installation de Python.

## Règles de contribution

- `main` et `develop` sont protégées : aucun commit direct (bloqué par pre-commit).
- Une branche par ticket Jira : `feature/EV-12-description-courte`.
- Les messages de commit citent la clé Jira : `EV-12: ajoute l'import CSV`.
- Chaque pull request demande **2 relectures** avant le merge.
- Aucun secret dans le dépôt : utiliser `.env` (ignoré par Git).
