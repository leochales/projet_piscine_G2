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
- Comme pour le modèle, seules les heures mesurées servent de valeur passée (`taux_couverture` > 0) : une heure interpolée du jeu d'entraînement compte comme absente. Le modèle et la référence sont ainsi comparés sur les mêmes données.
- Les décalages sont calculés sur tout le jeu avant de garder le jeu évalué : les premières heures du test utilisent les vraies valeurs de la validation.
- L'erreur n'est mesurée que sur les valeurs réellement mesurées (`consommation_kwh_brute`), jamais sur les valeurs interpolées.
- MAE et RMSE en kWh (`moyenne_kw` sur une heure vaut des kWh). WAPE = `Σ|erreur| / Σ réel`.
- `scores_reference(df, jeu)` renvoie ces scores pour un jeu donné : l'entraînement compare ses modèles à la référence sur le même découpage.

### Seuil retenu

Jeu de test (2024-09-12 12:00 → 2024-12-31), jeu d'empreinte `f2ee5c19efdb` (voir `rapport_qualite.json`) :

| Prévision | MAE | RMSE | WAPE |
|---|---|---|---|
| Semaine précédente (retenue) | 115,4 kWh | 255,3 kWh | **23,35 %** |
| Veille | 136,9 kWh | 282,7 kWh | 27,73 % |

La veille se trompe à chaque passage entre semaine et week-end. Les anomalies du jeu (pics, chutes, coupures) causent environ les deux tiers de l'erreur. Si les données changent (nouvelle version DVC, autre empreinte), relancer la commande et mettre ce tableau à jour.

## Variables du modèle (SMARTOPS-29)

`model/features.py` construit les variables à partir de lignes au format de `gold.consommation_horaire` (colonnes utilisées : `id_site`, `heure`, `moyenne_kw`, `taux_couverture`). Le même code sert à l'entraînement et à la prévision.

Entraînement :

```python
from model.features import construire_variables, moyennes_par_site, noms_variables

# Sur l'entraînement seulement, à enregistrer avec le modèle
moyennes = moyennes_par_site(train)
# Horizon 24 (24 h) ou 168 (7 jours)
df = construire_variables(df, moyennes, 24)
X = df[noms_variables(24, moyennes)]
```

Prévision : les heures à prévoir n'existent pas encore dans gold. Il faut d'abord les ajouter, vides, à la suite de l'historique. Leurs variables sont ensuite calculées à partir de l'historique :

```python
from model.features import ajouter_heures_a_prevoir

# Les 24 heures à partir de prochaine_heure, pour le modèle à 24 h
df = ajouter_heures_a_prevoir(historique, prochaine_heure, 24)
# Moyennes enregistrées avec le modèle
df = construire_variables(df, moyennes, 24)
X = df.loc[df["heure"] >= prochaine_heure, noms_variables(24, moyennes)]
```

`ajouter_heures_a_prevoir` :

- ajoute autant d'heures que l'horizon, pas plus : au-delà, les variables porteraient sur des heures encore inconnues. Pour 7 jours, appeler avec 168 et le modèle à 7 jours ;
- demande un début avec fuseau horaire, sur une heure pile (`10:00`, pas `10:37`) ;
- refuse un historique en retard. Chaque site doit avoir une mesure à l'heure qui précède le début, sinon les dernières heures à prévoir n'auraient pas toutes leurs variables. L'erreur nomme les sites en retard, y compris un site sans aucune mesure récente, au lieu de les prévoir à moitié ou de les faire disparaître. On peut les retirer de l'historique pour prévoir les autres ;
- ne garde que les 28 jours avant le début (`HISTORIQUE_UTILE`), le plus long retour en arrière des variables. Il suffit donc de lire ces 28 jours dans gold.

Règles :

- Horizons : 24 et 168 seulement. Un horizon plus court ferait entrer dans les variables des heures inconnues au moment de prévoir.
- Consommation de l'heure : `moyenne_kw` des heures mesurées (`taux_couverture` > 0), divisée par la moyenne du site sur l'entraînement (`conso_norm`), pour qu'un seul modèle serve à tous les sites. Une heure interpolée du jeu d'entraînement est traitée comme absente : en production, l'ETL ne comble jamais une heure entière, et elle serait absente de gold.
- Sites : ceux qui ont une moyenne d'entraînement valable (au moins une heure mesurée, moyenne non nulle). Les moyennes, enregistrées avec le modèle, servent de liste des sites. Un nouveau site est refusé tant que le modèle n'est pas réentraîné avec lui.
- Lags (24 h, 7, 14 et 28 jours) et moyennes glissantes (24 h, 7 jours) : seulement ceux qui sont connus au moment de prévoir, donc pris au moins `horizon` heures avant. À 7 jours, pas de lag de 24 h. Une moyenne glissante demande au moins 80 % d'heures connues, sinon elle reste vide.
- Calendrier et site : heure du jour, jour de la semaine et site en colonnes 0/1, toujours les mêmes colonnes, même si une valeur est absente des données.
- Heure du jour et jour de la semaine lus sur `heure` sans conversion en heure de Paris. Les horodatages du CSV et de l'API Mock sont l'heure du simulateur, sans changement d'heure, enregistrée comme de l'UTC (voir les règles du jeu d'entraînement). Le CSV n'a ni heure manquante en mars ni heure en double en octobre, et les bureaux y commencent à 8 h été comme hiver. Convertir en heure de Paris décalerait ce profil d'une heure l'été. Avec de vraies données en UTC, il faudra convertir en heure locale du site.
- Décalages dans le temps : les heures absentes de gold sont ajoutées vides avant de décaler, puis retirées. Un lag de 24 h prend donc toujours l'heure d'il y a 24 h, ou reste vide. La prévision de référence utilise le même calcul (`valeurs_passees`).
- Entrée refusée avec un message clair : colonne manquante, aucune ligne, même heure en double pour un site, site sans moyenne d'entraînement.

## Entraînement (SMARTOPS-31)

Depuis la racine du dépôt, après avoir construit le jeu (`python -m model.dataset`) :

```bash
python -m model.entrainement
```

Pour chaque horizon (24 h et 7 jours), le script :

1. construit les variables (`model/features.py`) sur tout le jeu, avec les moyennes par site calculées sur l'entraînement seulement ;
2. garde les heures mesurées (`taux_couverture` > 0), les seules qui servent à apprendre et à évaluer ;
3. entraîne Ridge et random forest sur le jeu `entrainement` ;
4. les compare sur la `validation`, avec les prévisions de référence, et retient celui qui a le plus petit WAPE ;
5. mesure le modèle retenu une seule fois sur le `test`, au total et site par site.

Il affiche les scores, le modèle retenu et le nombre d'heures concernées. Si le modèle retenu ne fait pas mieux que la référence sur la validation, il le signale et ne l'enregistre pas (voir « Enregistrement dans MLflow »).

### Règles

- Pas de fuite de données : les moyennes par site viennent de l'entraînement, le choix du modèle de la validation, et le test ne sert qu'une fois, à la fin.
- Règle de SMARTOPS-30 : le modèle retenu doit faire mieux que la semaine précédente, en WAPE global, sur la validation (`Resultat.bat_reference`). Les scores par site servent à vérifier les sites un par un, la règle porte sur le score global. La décision ne se prend pas sur le test : en relançant jusqu'à ce qu'un modèle passe, le test servirait plusieurs fois.
- Le modèle prévoit `conso_norm` (consommation divisée par la moyenne du site), qu'on remultiplie par la moyenne du site pour revenir en kWh. Un seul modèle sert ainsi aux sites de toutes les tailles.
- Une heure dont une variable manque (un lag pendant une panne, par exemple) est apprise et prévue quand même, comme en production. Le random forest accepte les cases vides. Pour Ridge, une case vide est remplacée par la moyenne de la colonne sur l'entraînement.
- Modèles et références sont notés sur les mêmes heures, avec le même calcul que la prévision de référence (`scores`) : celles où les références valables pour l'horizon existent. À 24 h, la veille et la semaine précédente. À 7 jours, la semaine précédente seulement : la veille n'est pas encore connue 7 jours à l'avance, elle n'est ni affichée ni utilisée pour écarter des heures. La référence retenue pour la règle de SMARTOPS-30 est la semaine précédente, valable aux deux horizons.
- Un site sans heure mesurée dans l'entraînement (mis en service après la date de coupure, par exemple) est écarté avec un message : il n'a pas de moyenne, le modèle ne peut pas le prévoir, mais il ne bloque pas les autres.
- Réglages simples, sans recherche : Ridge avec `alpha=1`, random forest de 100 arbres, au moins 50 lignes par feuille, `random_state=0` pour des résultats reproductibles. 50 lignes par feuille plutôt que 5 : sur la validation, le WAPE est égal ou meilleur (15,15 % contre 15,41 % à 24 h, 15,70 % contre 15,82 % à 7 jours) et le modèle pèse 12 Mo au lieu de 124, ce qui compte pour le stockage de MLflow (SMARTOPS-32).

### Résultats

Jeu d'empreinte `f2ee5c19efdb`. Le random forest est retenu aux deux horizons (validation : 15,2 % de WAPE à 24 h et 15,7 % à 7 jours, contre 19,5 % et 20,1 % pour Ridge).

Sur le test, sur les mêmes heures que la référence :

| Horizon | Semaine précédente | Random forest |
|---|---|---|
| 24 h | 115,6 kWh de MAE, **23,40 %** de WAPE | 79,9 kWh, **16,18 %** |
| 7 jours | 115,4 kWh, **23,35 %** | 81,5 kWh, **16,50 %** |

Le modèle fait environ 30 % d'erreur en moins que la référence, et il fait mieux sur chacun des 7 sites (WAPE à 24 h de 12,5 % pour SITE005 à 19,8 % pour SITE002). Le 7 jours est presque aussi bon que le 24 h : la consommation suit surtout un rythme par semaine, que les deux modèles voient.

Sur 17 980 heures mesurées du test, 2 013 ont une variable manquante à 24 h (1 639 à 7 jours) et sont prévues quand même. Celles qui n'ont pas de référence sont exclues de la comparaison : 843 à 24 h (veille ou semaine précédente manquante), 431 à 7 jours (semaine précédente manquante). À 7 jours, la référence retrouve donc les 23,35 % de SMARTOPS-30.

L'erreur restante vient surtout des anomalies du jeu (pics, chutes, coupures), imprévisibles : le RMSE vaut plus du double de la MAE, signe de quelques heures très ratées plutôt que d'une petite erreur partout.

## Enregistrement dans MLflow (SMARTOPS-32)

`python -m model.entrainement` enregistre aussi les modèles dans MLflow, comme `model.dataset` enregistre le jeu. Sans `MLFLOW_TRACKING_URI` ni `--sans-mlflow`, la commande s'arrête : MLflow écrirait sinon dans un dossier `mlruns` local.

Avec Docker, la stack locale démarrée et le jeu construit :

```bash
docker compose -f compose-local.yml run --rm --build entrainement
```

Sans Docker, avec le MLflow local (http://localhost/mlflow) :

```bash
MLFLOW_TRACKING_URI=http://localhost/mlflow python -m model.entrainement
```

Sous Windows (PowerShell) : `$env:MLFLOW_TRACKING_URI="http://localhost/mlflow"`, puis la commande, avec `$env:PYTHONIOENCODING="utf-8"` (voir le jeu d'entraînement).

Sur la VM, le workflow **Dataset** (Actions → Dataset → Run workflow) entraîne et enregistre le modèle juste après avoir construit le jeu, dans le MLflow de l'environnement (service `entrainement` de `compose-prod.yml`, voir `infra/runner.md`).

Pour chaque horizon, dans l'expérience `prevision-consommation` :

1. un run `prevision-24h` ou `prevision-168h`, toujours : modèle retenu et réglages, scores de validation et de test du modèle et des références (`validation_random_forest_WAPE`, `test_baseline_semaine_MAE`…), empreinte du jeu (`empreinte_jeu`, lue dans `rapport_qualite.json`), tag `bat_reference` et une description qui rappelle d'où viennent les scores ;
2. si le modèle bat la référence sur la validation, il est réentraîné sur toutes les données (entraînement, validation et test) et enregistré comme nouvelle version du modèle `prevision-conso-24h` ou `prevision-conso-168h`. Les moyennes par site, recalculées sur ces données, sont enregistrées dans le même run (`moyennes_par_site.json`) ;
3. l'alias `production` passe sur cette nouvelle version. Sinon, aucune version n'est créée et l'alias ne bouge pas.

La génération des prévisions (SMARTOPS-33) charge la version `production` :

```python
from model.registre import charger

production = charger(24)  # ou 168 : modele, moyennes et version
```

Les moyennes servent à `construire_variables` (normalisation et liste des sites), puis `production.modele.predict` donne `conso_norm`, à remultiplier par la moyenne du site. `production.version` (par exemple `prevision-conso-24h/3`) est écrit avec chaque prévision.

## Prévisions horaires (SMARTOPS-33)

Le service `prevision` lance `python -m model.prevision` chaque heure à hh:05 (`model/crontab`, supercronic, comme l'ETL). Il écrit dans `gold.prediction` les prévisions de chaque site actif, de l'heure pleine suivante jusqu'à 7 jours, avec la fourchette. L'API (`GET /sites/{id}/predictions`) lit la plus récente de chaque heure.

Avec Docker, la stack locale démarrée et un modèle enregistré (voir ci-dessus), pour lancer une prévision sans attendre hh:05 :

```bash
docker compose -f compose-local.yml exec prevision python -m model.prevision
```

### Règles

- Les versions `production` des deux modèles se partagent les heures : le modèle 24 h prévoit les 24 premières heures, le modèle 7 jours les heures 25 à 168. Chaque heure a une seule prévision par exécution, celle du modèle le plus précis disponible ; `version_modele` dit lequel. Le partage se fait site par site : sans version `production` du modèle 24 h, ou pour un site que cette version ne connaît pas (versions de dates différentes), le modèle 7 jours prévoit aussi les 24 premières heures.
- Historique : `gold.consommation_horaire` des sites actifs, sur les 28 derniers jours et un peu plus (`HISTORIQUE_UTILE`), heure en cours comprise. Les variables sont celles de l'entraînement (`model/features.py`).
- Un site actif sans mesure dans l'heure en cours (capteur en panne, ETL en retard, y compris une panne plus longue que l'historique lu) n'est pas prévu, avec un avertissement dans les logs : ses dernières variables porteraient sur des heures inconnues. Un site inconnu du modèle (ajouté après l'entraînement) non plus : il faut réentraîner. Les autres sites sont prévus quand même.
- Fourchette : centiles 10 et 90 des prévisions des 100 arbres du random forest, remultipliés par la moyenne du site. Elle traduit le désaccord entre les arbres, pas une garantie que 80 % des heures réelles y tombent. Si la prévision (moyenne des arbres) sort de ces centiles, la borne est ramenée à la prévision : la base exige `basse <= prévue <= haute`. Un modèle Ridge ne donne pas de fourchette (bornes NULL).
- Prévision et bornes jamais négatives.
- Pic de l'heure (SMARTOPS-104) : le jeu d'entraînement n'a pas de `pic_kw` (une mesure par heure), aucun modèle n'apprend donc le pic des minutes. `pic_prevu_kw` vaut la consommation prévue (kWh d'une heure = kW moyens) multipliée par le rapport pic/moyenne du site, médiane sur `HISTORIQUE_UTILE`.
- Le pic d'une heure passée est son **pic soutenu** : la plus forte valeur tenue par 3 minutes mesurées consécutives (`silver.silver_readings.consumption_kw_raw`, jamais imputée), avec la règle des pics de l'ETL (plus de 5 minutes sans mesure coupent la série). Le pic d'une seule minute (`gold.consommation_horaire.pic_kw`) dépasserait le seuil bien plus souvent que les alertes réelles : sur 7 jours de mesures simulées, 8 à 19 heures par jour et par site, contre aucune avec le pic soutenu, pour 0,1 à 0,7 alerte réelle par jour. La moyenne est `moyenne_kw` de `gold.consommation_horaire`. Seules comptent les heures terminées dont au moins 80 % des minutes sont mesurées (`COUVERTURE_MIN_MOYENNE`, minutes imputées exclues) : une heure en panne ou imputée a un pic proche de sa moyenne.
- Le rapport est pris par heure de la journée si elle a au moins 3 heures mesurées, sinon celui du site, et vaut au moins 1. `pic_bas_kw` et `pic_haut_kw` appliquent le même rapport aux bornes de consommation (NULL sans fourchette).
- Un site avec moins de 24 heures mesurées (ETL démarré depuis peu, longue panne) n'a pas de pic prévu : `pic_prevu_kw` NULL et `pic_prevu` faux, avec un avertissement dans les logs. Ses prévisions de consommation sont écrites quand même.
- `pic_prevu` est vrai quand `pic_prevu_kw` atteint le seuil d'alerte du site, `seuil_alerte_pct` % de `capacite_kw` (`app.site`) : le même seuil que la détection des pics mesurés par l'ETL.
- Sans aucune version `production` (avant le premier entraînement), le job écrit un avertissement et rien d'autre. Si MLflow ou la base ne répondent pas, il s'arrête en erreur, visible dans les logs.
- Chaque exécution ajoute ses lignes (`calculee_le`) : l'historique des prévisions est gardé pour comparer prévu et réel.
- Cache des modèles (`MODELE_CACHE_DIR`, volume `modele_cache` du service) : une version est téléchargée une seule fois, à sa première utilisation. Ensuite, chaque heure, MLflow ne sert qu'à lire le numéro de la version `production` (deux petites requêtes) et le modèle est lu sur le disque. Les anciennes versions et les téléchargements abandonnés sont supprimés une fois inutilisés depuis une heure (`DELAI_NETTOYAGE`), après le chargement : deux lancements qui se chevauchent (à la main pendant le cron, alias déplacé entre les deux) n'effacent jamais les fichiers l'un de l'autre. Le nom d'une version contient son run, pour qu'un modèle supprimé puis réenregistré (qui repart à la version 1) ne resserve pas l'ancien fichier. Sans `MODELE_CACHE_DIR`, le modèle est lu dans MLflow à chaque lancement.
