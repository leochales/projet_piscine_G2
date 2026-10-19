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

## Règles de contribution

- `main` est protégée : aucun push direct.
- Une branche par ticket Jira : `feature/EV-12-description-courte`.
- Les messages de commit citent la clé Jira : `EV-12: ajoute l'import CSV`.
- Chaque pull request demande **2 relectures** avant le merge.
- Aucun secret dans le dépôt : utiliser `.env` (ignoré par Git).
