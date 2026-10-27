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

Avec enregistrement dans le MLflow local (http://localhost/mlflow). Sans `MLFLOW_TRACKING_URI` ni `--sans-mlflow`, la commande s'arrête : MLflow écrirait sinon dans un dossier `mlruns` local.

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
| `rapport_qualite.json` | Valeurs manquantes, imputées et nulles, au total, par site et par jeu, et empreinte du jeu et des anomalies |

### Règles

- Horodatages sans fuseau lus comme de l'UTC, comme ceux de l'API Mock ; un fuseau explicite (`Z`, `+01:00`) est converti en UTC.
- Première version sans météo : seule la consommation est gardée.
- Mêmes valeurs que gold, qui agrège des minutes : une heure mesurée du CSV compte pour 60 mesures (`nb_mesures` à 0 ou 60, `taux_couverture` à 0 ou 1) et `moyenne_kw` vaut la consommation de l'heure. `pic_kw` reste vide : le pic des minutes est inconnu avec une mesure par heure. `heure_complete` est vrai partout : en gold, il indique que l'heure est terminée (60 minutes en silver), avec ou sans consommation.
- Une heure interpolée garde sa valeur pour l'entraînement (`methode_imputation`), mais compte 0 mesure et `nb_imputees` vaut toujours 0 : l'ETL n'impute que des trous de quelques minutes, jamais une heure entière.
- Aucune ligne supprimée. Une consommation négative devient manquante ; un trou de 2 heures au plus est comblé par interpolation linéaire (`linear_interpolation`) ; un trou plus long reste vide, avec `taux_couverture = 0`. Les consommations à 0 (coupures étiquetées) sont gardées.
- Découpage chronologique 70 / 15 / 15 sur des heures communes à tous les sites. L'imputation se fait dans chaque jeu : un trou à la frontière n'est pas comblé avec une valeur du jeu suivant.

| Jeu | Période | Heures × sites |
|---|---|---|
| `entrainement` | 2023-01-01 00:00 → 2024-05-25 23:00 | 85 848 |
| `validation` | 2024-05-26 00:00 → 2024-09-12 11:00 | 18 396 |
| `test` | 2024-09-12 12:00 → 2024-12-31 00:00 | 18 403 |

### MLflow

Chaque construction crée un run dans l'expérience `jeu-entrainement` : les trois jeux en entrée (contextes `entrainement`, `validation`, `test`), les paramètres (source, imputation, dates de découpage, empreinte), les comptages du rapport et les trois fichiers en artefacts. L'empreinte ne change que si le contenu du jeu ou des anomalies change.

### Tests

```bash
python -m pytest -q model
```

## Prévision de référence (SMARTOPS-30)

Deux prévisions naïves servent de seuil au modèle : la consommation de la veille et celle de la semaine précédente, à la même heure, site par site. Une version du modèle n'est gardée que si elle fait mieux.

Depuis la racine du dépôt, après avoir construit le jeu (`python -m model.dataset`) :

```bash
python -m model.baseline              # scores sur le jeu de test
python -m model.baseline --jeu validation
```

Le jeu est lu dans `DATASET_OUTPUT_DIR` (`data/processed` par défaut), comme `model.dataset` l'écrit. `--chemin` donne un autre fichier.

### Règles

- La valeur passée est cherchée à l'heure exacte (24 h ou 168 h avant), pas 24 lignes plus haut : si cette heure manque, par exemple un trou dans `gold.consommation_horaire`, la prévision reste vide et l'heure est exclue du score. Le script affiche combien d'heures sont exclues.
- Les décalages sont calculés sur tout le jeu avant de garder le jeu évalué : les premières heures du test utilisent les vraies valeurs de la validation.
- L'erreur n'est mesurée que sur les valeurs réellement mesurées (`consommation_kwh_brute`), jamais sur les valeurs interpolées.
- MAE et RMSE en kWh (`moyenne_kw` sur une heure vaut des kWh). WAPE = `Σ|erreur| / Σ réel`.
- `scores_reference(df, jeu)` renvoie ces scores pour un jeu donné : l'entraînement compare ses modèles à la référence sur le même découpage.

### Seuil retenu

Jeu de test (2024-09-12 12:00 → 2024-12-31), jeu d'empreinte `f2ee5c19efdb` (voir `rapport_qualite.json`) :

| Prévision | MAE | RMSE | WAPE |
|---|---|---|---|
| Semaine précédente (retenue) | 115,3 kWh | 255,2 kWh | **23,31 %** |
| Veille | 137,1 kWh | 282,7 kWh | 27,74 % |

La veille se trompe à chaque passage entre semaine et week-end. Les anomalies du jeu (pics, chutes, coupures) causent environ les deux tiers de l'erreur. Si les données changent (nouvelle version DVC, autre empreinte), relancer la commande et mettre ce tableau à jour.

## Variables du modèle (SMARTOPS-29)

`model/features.py` construit les variables à partir de lignes au format de `gold.consommation_horaire`. Le même code sert à l'entraînement et à la prévision.

Entraînement :

```python
from model.features import construire_variables, moyennes_par_site, noms_variables

moyennes = moyennes_par_site(train)  # sur l'entraînement seulement
df = construire_variables(df, moyennes, 24)  # horizon 24 (24 h) ou 168 (7 jours)
X = df[noms_variables(24)]
```

Prévision : les heures à prévoir n'existent pas encore dans gold. Il faut d'abord les ajouter, vides, à la suite de l'historique. Leurs variables sont ensuite calculées à partir de l'historique :

```python
from model.features import ajouter_heures_a_prevoir

df = ajouter_heures_a_prevoir(historique, debut=prochaine_heure, nb_heures=24)
df = construire_variables(df, moyennes, 24)  # moyennes enregistrées avec le modèle
X = df.loc[df["heure"] >= prochaine_heure, noms_variables(24)]
```

- Consommation de l'heure : `moyenne_kw`, divisée par la moyenne du site sur l'entraînement (`conso_norm`), pour qu'un seul modèle serve aux 7 sites.
- Lags (24 h, 7, 14 et 28 jours) et moyennes glissantes (24 h, 7 jours) : seulement ceux qui sont connus au moment de prévoir, donc pris au moins `horizon` heures avant. À 7 jours, pas de lag de 24 h. Une moyenne glissante demande au moins 80 % d'heures connues, sinon elle reste vide.
- Calendrier et site : heure du jour, jour de la semaine et site en colonnes 0/1, toujours les mêmes colonnes, même si une valeur est absente des données.
- Heure du jour et jour de la semaine lus sur `heure` sans conversion en heure de Paris. Les horodatages du CSV et de l'API Mock sont l'heure du simulateur, sans changement d'heure, enregistrée comme de l'UTC (voir les règles du jeu d'entraînement). Le CSV n'a ni heure manquante en mars ni heure en double en octobre, et les bureaux y commencent à 8 h été comme hiver. Convertir en heure de Paris décalerait ce profil d'une heure l'été. Avec de vraies données en UTC, il faudra convertir en heure locale du site.
- Décalages dans le temps : les heures absentes de gold sont ajoutées vides avant de décaler, puis retirées. Un lag de 24 h prend donc toujours l'heure d'il y a 24 h, ou reste vide. La prévision de référence utilise le même calcul (`valeurs_passees`).
- Entrée refusée avec un message clair : aucune ligne, site absent de la liste du modèle, ou site sans moyenne d'entraînement (absente ou nulle).
