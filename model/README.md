# Modèle de prévision

## Jeu d'entraînement (SMARTOPS-93)

Le modèle s'entraîne sur l'historique CSV fourni avec le sujet, mis au format de `gold.consommation_horaire` : c'est la table que le modèle lit en production, une ligne par site et par heure.

### Données brutes

Les fichiers sont dans `data/raw/` (ignoré par Git, 13 Mo), versionnés par DVC : `data/raw.dvc` donne leur version. Pour les récupérer, avec `pip install "dvc[ssh]==3.67.1"` et l'alias SSH `enervision-vm` (voir `infra/runner.md`, section « Jeu d'entraînement du modèle ») :

```bash
dvc pull
```

Fichiers :

- `all_sites_combined.csv` : 7 sites × 17 521 heures, du 2023-01-01 au 2024-12-31 (SITE007 n'existe que dans ce fichier) ;
- `SITE001_metadata.json` à `SITE007_metadata.json` : anomalies étiquetées.

### Construire le jeu avec Docker (recommandé)

Depuis la racine du dépôt, la stack locale démarrée (MLflow sur http://localhost/mlflow) :

```bash
docker compose -f compose-local.yml run --rm --build dataset
```

Le service `dataset` (profil `jobs`) ne démarre jamais avec `docker compose up` : il construit le jeu puis s'arrête. Il lit `data/raw/` en lecture seule, écrit dans `data/processed/` et enregistre le run dans le MLflow de la stack.

En production, le jeu se construit avec le workflow **Dataset** (Actions → Dataset → Run workflow), dans l'image `enervision-model` déployée. Stockage DVC sur la VM et accès à MLflow : voir `infra/runner.md`, section « Jeu d'entraînement du modèle ».

### Construire le jeu sans Docker

Depuis la racine du dépôt, avec le venv activé (`pip install -r model/requirements.txt`) :

```bash
python -m model.dataset --sans-mlflow
```

Avec enregistrement dans le MLflow local (http://localhost/mlflow) :

```bash
MLFLOW_TRACKING_URI=http://localhost/mlflow python -m model.dataset
```

Sous Windows, ajouter `PYTHONIOENCODING=utf-8` : MLflow affiche un emoji en fin de run que la console ne sait pas écrire.

Dossiers : `--raw-dir` / `DATASET_RAW_DIR` (`data/raw` par défaut) et `--out-dir` / `DATASET_OUTPUT_DIR` (`data/processed` par défaut).

### Fichiers produits (`data/processed/`)

| Fichier | Contenu |
|---|---|
| `dataset.parquet` | Colonnes de `gold.consommation_horaire`, plus `consommation_kwh_brute`, `methode_imputation` et `jeu` |
| `anomalies.parquet` | Anomalies étiquetées (`id_site`, `debut`, `type`, `gravite`, `description`) |
| `rapport_qualite.json` | Valeurs manquantes, imputées et nulles, au total, par site et par jeu, et empreinte du jeu |

### Règles

- Horodatages sans fuseau lus comme de l'UTC, comme ceux de l'API Mock.
- Première version sans météo : seule la consommation est gardée.
- Aucune ligne supprimée. Une consommation négative devient manquante ; un trou de 2 heures au plus est comblé par interpolation linéaire (`linear_interpolation`) ; un trou plus long reste vide, avec `taux_couverture = 0`. Les consommations à 0 (coupures étiquetées) sont gardées.
- Découpage chronologique 70 / 15 / 15 sur des heures communes à tous les sites :

| Jeu | Période | Heures × sites |
|---|---|---|
| `entrainement` | 2023-01-01 00:00 → 2024-05-25 23:00 | 85 848 |
| `validation` | 2024-05-26 00:00 → 2024-09-12 11:00 | 18 396 |
| `test` | 2024-09-12 12:00 → 2024-12-31 00:00 | 18 403 |

### MLflow

Chaque construction crée un run dans l'expérience `jeu-entrainement` : les trois jeux en entrée (contextes `entrainement`, `validation`, `test`), les paramètres (source, imputation, dates de découpage, empreinte), les comptages du rapport et les trois fichiers en artefacts. L'empreinte ne change que si le contenu du jeu change.

### Tests

```bash
python -m pytest -q model
```
