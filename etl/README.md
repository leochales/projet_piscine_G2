# ETL

L'ETL récupère les mesures des 7 sites dans l'API Mock, les nettoie et prépare les données que lisent le dashboard, l'API et le modèle. Il tourne chaque minute dans le conteneur `etl`, sans intervention.

Les données passent par trois couches de la base PostgreSQL :

| Couche | Contenu | Qui la lit |
|---|---|---|
| `bronze` | Mesures brutes de l'API Mock, jamais modifiées | silver |
| `silver` | Une ligne par site et par minute, valeurs contrôlées, trous rendus visibles et imputés s'ils sont courts | gold, modèle (pic des heures passées) |
| `gold` | Données prêtes à afficher : consommation horaire, dernière mesure, état des capteurs, alertes, recommandations | API, modèle, Grafana |

La stratégie générale (endpoints de l'API Mock, rythme, valeurs nulles) est aussi décrite sur la page Confluence « Pipeline ETL stratégie ».

## Planning

Le planning est dans [`crontab`](crontab), lancé par supercronic (`Dockerfile`). Chaque minute, six étapes s'enchaînent dans cet ordre :

| # | Commande | Lit | Écrit | Ticket |
|---|---|---|---|---|
| 1 | `python -m etl.collect` | API Mock `GET /api/v1/sites/{id}/current`, `app.site` | `bronze.raw_readings` | SMARTOPS-21 |
| 2 | `python -m etl.silver` | `bronze.raw_readings` | `silver.silver_readings`, `silver.rejected_readings` | SMARTOPS-24 |
| 3 | `python -m etl.gold_hourly` | `silver.silver_readings` | `gold.consommation_horaire` | SMARTOPS-25 |
| 4 | `python -m etl.gold_latest` | `silver.silver_readings`, API Mock `GET /api/v1/sensors/status` | `gold.derniere_mesure`, `gold.etat_capteur` | SMARTOPS-23 |
| 5 | `python -m etl.gold_alerts` | `silver.silver_readings`, `app.site` (seuils) | `gold.alerte` | SMARTOPS-26 |
| 6 | `python -m etl.recommandations` | `gold.alerte` | `gold.recommandation` | SMARTOPS-40 |

Les étapes sont séparées par `;` et non `&&` : si une étape échoue (API Mock injoignable, par exemple), les suivantes traitent quand même ce qui est déjà disponible.

Au démarrage du conteneur, l'amorçage (`python -m etl.bootstrap`, SMARTOPS-22) tourne en arrière-plan, en même temps que le cron. Il ne retarde pas la collecte.

Les prévisions ne sont pas faites par l'ETL. Elles sont écrites chaque heure par le service `prevision` (voir [`model/README.md`](../model/README.md)).

## Lancer l'ETL

L'ETL démarre avec la stack :

```bash
docker compose -f compose-local.yml up -d
```

Pour lancer une étape à la main, sans attendre la minute suivante :

```bash
docker compose -f compose-local.yml exec etl python -m etl.collect
docker compose -f compose-local.yml exec etl python -m etl.bootstrap
```

`ETL_ENABLED=false` dans le `.env` (ou la variable `DEV_ETL_ENABLED` / `PROD_ETL_ENABLED` sur la VM) garde le conteneur démarré sans lancer aucun job.

## Les étapes

### 1. Collecte (`collect.py`)

- Les sites à collecter sont ceux de `app.site` avec le statut `active`. L'ETL ne les crée pas : ils sont déclarés par l'application (`db/08_sites_demo.sql` pour les 7 sites de démo). Un site de l'API Mock absent de `app.site` est ignoré et signalé dans les logs.
- Seul `/current` sert à la collecte. `/readings` tire un historique aléatoire, différent à chaque appel. S'en servir pour combler un trou mettrait des valeurs inventées dans bronze et cacherait les vraies coupures.
- La clé d'une mesure est la minute pleine (UTC) de notre horloge, pas l'horodatage de l'API Mock, qui retarde d'environ 31 secondes. Le payload brut est gardé tel quel, avec son horodatage exact.
- La contrainte unique `(id_site, horodatage)` rend la collecte idempotente : deux passages dans la même minute ne gardent que la première mesure.
- Un site sans mesure depuis 10 minutes (`STALE_THRESHOLD`) est signalé dans les logs.

### Amorçage d'une base neuve (`bootstrap.py`)

Sur une base vide, le dashboard et le modèle n'auraient rien à montrer. L'amorçage charge, avec `/readings`, les 7 derniers jours de chaque site qui n'a pas encore été amorcé.

- Les mesures amorcées sont marquées `"_source": "readings_amorcage"` dans bronze.
- Il ne remplit que la période avant la première mesure du site. Il ne comble jamais un trou de collecte, qui doit rester visible.
- Il est rejouable : un site déjà amorcé, ou qui a déjà 7 jours de mesures, n'est pas réamorcé.
- Sa durée est bornée à 5 minutes (`BOOTSTRAP_DEADLINE`).

### 2. Nettoyage bronze → silver (`silver.py`)

Silver contient une ligne par site et par minute, y compris les minutes sans mesure (`bronze_id` vide). Un trou de collecte devient ainsi visible. Voir la partie [Qualité des données](#qualité-des-données).

Chaque passage retraite les 10 dernières minutes déjà en silver (`REPROCESS_MARGIN`) : un trou est imputé dès que la mesure qui le suit arrive. Un long retard est rattrapé sur plusieurs passages (8 jours au plus par passage et par site).

### 3. Consommation horaire (`gold_hourly.py`)

Le calcul est fait en SQL par `gold.calculer_consommation_horaire()` (`db/12_gold_horaire.sql`).

| Colonne | Calcul |
|---|---|
| `consommation_kwh` | Somme des kW × 1/60 h sur les minutes qui ont une consommation, mesurée ou imputée |
| `moyenne_kw`, `pic_kw` | Moyenne et maximum des minutes de l'heure |
| `nb_mesures`, `nb_imputees` | Minutes mesurées et minutes imputées |
| `taux_couverture` | `nb_mesures / 60`. Sous 1, les kWh sont sous-estimés |
| `heure_complete` | Silver contient les 60 minutes de l'heure |

L'heure en cours est mise à jour chaque minute. L'heure précédente est recalculée aussi, pour prendre en compte une imputation tardive.

Le coût en euros n'est pas stocké. L'API le calcule à partir des kWh et de `PRIX_KWH_EUR` (0,14 € par défaut) : un changement de tarif ne demande pas de recalculer gold.

### 4. Dernière mesure et état des capteurs (`gold_latest.py`)

- `gold.derniere_mesure` garde la dernière mesure transmise de chaque site (`db/13_gold_derniere_mesure.sql`). Un site qui ne transmet plus garde sa dernière mesure, dont l'heure vieillit.
- `gold.etat_capteur` vient de `GET /api/v1/sensors/status`. Si l'API Mock ne répond pas, l'état n'est pas modifié et garde sa date `mis_a_jour_le`.
- Le bandeau « sites qui ne transmettent plus » du dashboard lit la vue `gold.etat_site`. Elle distingue un site muet d'une collecte arrêtée (ETL arrêté, API Mock injoignable) : dans ce cas, `collecte_a_jour` est faux et `transmet` est inconnu pour tous les sites.

### 5. Alertes (`gold_alerts.py`)

La détection est faite en SQL par `gold.detecter_alertes()` (`db/17_gold_alertes.sql`). Une alerte commence après 3 minutes en défaut consécutives et se termine après 3 minutes sans défaut.

| Type | Défaut | Sévérité |
|---|---|---|
| `threshold` | Consommation mesurée au-dessus du seuil du site (`app.site.seuil_alerte_pct`) | `high`, `critical` dès 110 % de la capacité |
| `sensor` | Capteur de consommation ou capteur électrique en panne, lu dans les raisons des valeurs manquantes de silver | `high` (consommation), `medium` (électrique) |

Les seuils par type de site et les règles de détail (trous de plus de 5 minutes, alerte qui garde son identifiant) sont dans la section « Base de données » du [README racine](../README.md#base-de-données).

Les alertes de l'API Mock ne sont pas reprises : elles sont tirées au hasard à chaque appel, sans identifiant stable. Les alertes de pic prévu (`predicted_peak`) sont créées par le modèle, pas par l'ETL.

### 6. Recommandations (`recommandations.py`)

Les recommandations viennent de règles simples, pas du modèle. Chaque alerte en cours reçoit la recommandation de la règle qui correspond à son type et à sa sévérité. Les règles et le calcul sont en base (`db/18_gold_recommandations.sql`).

| Règle | Type d'alerte | Sévérité | Recommandation |
|---|---|---|---|
| `threshold_critical` | `threshold` | `critical` | Délestage d'urgence |
| `threshold` | `threshold` | toutes | Réduire la charge |
| `spike_critical` | `spike` | `critical` | Pic critique : intervenir sur le site |
| `spike` | `spike` | toutes | Analyser le pic de consommation |
| `predicted_peak` | `predicted_peak` | toutes | Anticiper le pic prévu |
| `anomaly` | `anomaly` | toutes | Diagnostiquer l'anomalie |
| `outage` | `outage` | toutes | Faire intervenir la maintenance |
| `sensor` | `sensor` | toutes | Vérifier le capteur |
| `alerte_generique` | autre | toutes | Examiner l'alerte |

La règle la plus précise gagne : la règle exacte (type et sévérité), sinon celle du type, sinon la règle générique.

Le gain estimé (SMARTOPS-90) n'est calculé que pour les dépassements de seuil (`threshold`, `spike`, `predicted_peak`) :

```
gain (€) = (valeur atteinte − seuil) kW × 1 h × prix du kWh
```

C'est l'énergie évitée en ramenant la consommation au seuil pendant une heure. Une alerte d'une heure et une alerte de cinq heures au même maximum ont le même gain : c'est un choix du MVP. Pour les autres types, le gain reste vide.

Tant que personne n'a décidé, une recommandation suit son alerte (sévérité, valeur, gain). Une fois acceptée ou refusée, elle ne change plus. Les économies du mois affichées par le dashboard ne comptent que les recommandations acceptées.

## Qualité des données

Le jeu de l'API Mock contient des défauts volontaires : capteurs en panne, pertes réseau, maintenances, bruit. L'ETL ne supprime aucune mesure. Il les classe, les signale et ne comble que les trous courts.

| Contrôle | Où | Ce qui se passe |
|---|---|---|
| Clé illisible (site, horodatage) | collecte (`ReadingKey`, `schemas.py`) | Mesure refusée, rien n'est écrit en bronze |
| Payload mal formé | silver (`EnergyReading`, `schemas.py`) | Mesure en quarantaine dans `silver.rejected_readings`, avec ses erreurs. La minute est traitée comme manquante (`rejected_reading`) |
| Valeur hors plage physique | silver (`RANGES`, `silver.py`) | Valeur mise à vide, avec la raison `<champ>_out_of_range` |
| Minute sans mesure | silver | Ligne gardée, avec la raison `no_reading` |
| Valeur nulle envoyée par l'API Mock | silver | Raison reprise de l'API : `consumption_sensor_failure`, `electrical_sensor_failure`, `temperature_sensor_failure`, `humidity_sensor_failure`, `network_loss` |

Plages physiques contrôlées :

| Champ | Plage acceptée |
|---|---|
| `voltage_v` | 360 à 440 V (400 V triphasé ± 10 %, EN 50160) |
| `current_a` | 0 à 10 000 A |
| `power_factor` | 0 à 1 |
| `temperature_celsius` | −40 à 60 °C |
| `humidity_percent` | 0 à 100 % |
| `consumption_kw` | 0 à 2 fois la capacité du site (`MAX_LOAD_RATIO`) |

Une consommation au-dessus de la capacité est gardée (`load_percent` peut dépasser 100) : ce sont les pics à détecter. Seule une valeur au-delà de 2 fois la capacité est jugée physiquement impossible.

Seule la consommation est imputée, par interpolation linéaire, pour les trous de 5 minutes au plus (`MAX_IMPUTED_GAP`). La page Confluence « Pipeline ETL stratégie » prévoit 2 minutes au plus (« moins de 3 mesures »). Le choix entre les deux reste à trancher (SMARTOPS-28) : soit passer la constante à 2, soit garder 5 et corriger la page. La valeur brute reste dans `consumption_kw_raw`, la valeur imputée dans `consumption_kw_imputed`, et la méthode dans `imputation_method`. L'interpolation utilise la mesure suivante : elle convient pour la consommation d'une heure passée, pas pour les variables du modèle, qui ne connaît pas le futur. Quand le modèle lit silver (pic soutenu des heures passées), il prend donc `consumption_kw_raw`, jamais la valeur imputée.

La part de minutes imputées sur les dernières 24 heures est suivie dans Grafana (panneau « Taux d'imputation » du tableau métier).

## Automatisation et traçabilité

| Besoin | Réponse |
|---|---|
| Tourner sans intervention | cron toutes les minutes (supercronic), amorçage automatique au démarrage |
| Pouvoir rejouer sans risque | Collecte idempotente (contrainte unique), silver et gold recalculés par upsert, amorçage qui ne réamorce jamais un site |
| Savoir ce qui s'est passé | Logs JSON (`common/logs.py`) envoyés à Loki, filtrables par service et par niveau dans Grafana |
| Détecter un échec | Code de sortie de chaque étape (par exemple `collect` : 1 si tous les sites échouent, 2 si aucun site n'est déclaré), avertissement pour un site sans mesure depuis 10 minutes, panneaux « Dernière collecte » et « Mesures collectées » de Grafana |
| Garder la donnée d'origine | Bronze n'est jamais modifié. Silver garde la valeur brute à côté de la valeur imputée. Les mesures refusées sont gardées en quarantaine |
| Limiter les droits | Compte PostgreSQL `etl` : écriture dans bronze, silver et dans les tables de gold qu'il calcule, lecture de 3 colonnes de `app.site` seulement (`db/06_roles.sql`) |

## Tests

| Tests | Ce qu'ils vérifient | Lancés par |
|---|---|---|
| `etl/tests/` (pytest) | Collecte, amorçage, schémas, nettoyage silver (dont l'imputation des trous, testée par rapport à `MAX_IMPUTED_GAP` et non avec des valeurs fixes), appels aux fonctions SQL | hook `pytest-etl` au push, `pre-commit.yml` en CI |
| `db/tests/test_gold_horaire.sql` | Consommation horaire | `images.yml` |
| `db/tests/test_gold_derniere_mesure.sql` | Dernière mesure | `images.yml` |
| `db/tests/test_gold_alertes.sql` | Détection des dépassements et des pannes de capteur | `images.yml` |
| `db/tests/test_gold_recommandations.sql` | Choix de la règle, gain estimé, recommandation figée après décision | `images.yml` |

En local :

```bash
.venv/bin/python -m pytest -q etl
```

## Limites connues

- Pas de purge : bronze et silver gardent tout l'historique (SMARTOPS-91).
- Le volume d'une minute de collecte pour 7 sites est petit. Le cron d'un seul conteneur suffit. Un orchestrateur comme Airflow serait disproportionné (voir la page Confluence « Technos »).
- Le facteur CO₂ affiché par le dashboard (0,052 kg/kWh) est une constante du front, l'API Mock ne fournit pas cette donnée.
