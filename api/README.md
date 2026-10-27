# API EnerVision

### Documentation

Avec Docker Compose, l'API passe par Traefik (http://localhost) ; lancée en local avec uvicorn, elle est sur http://localhost:8000.

| URL (Docker) | URL (uvicorn) | Contenu |
|---|---|---|
| http://localhost/api/docs | http://localhost:8000/api/docs | Swagger UI (tester les routes) |
| http://localhost/api/openapi.json | http://localhost:8000/api/openapi.json | Schéma OpenAPI |

Un paramètre de requête que la route ne déclare pas est refusé (422) : une faute de frappe (`?id_stie=…`) ne renvoie pas toutes les données sans filtre.

### Authentification

Toutes les routes `/api` demandent un jeton d'accès Keycloak, sauf `/api/health` et la documentation (`/api/docs`, `/api/openapi.json`). Le front l'envoie dans l'en-tête `Authorization: Bearer <jeton>`. Le fonctionnement complet est décrit sur la page Confluence « Authentification (Keycloak) ».

L'API vérifie (`api/auth.py`) :

- la signature (RS256), avec les clés publiques lues en interne (`KEYCLOAK_URL_INTERNE`) et gardées en cache ;
- l'émetteur (`iss`), qui doit valoir l'adresse publique de Keycloak (`KEYCLOAK_EMETTEUR`, calculée à partir de `FRONT_URL` dans les compose) ;
- l'audience (`enervision-api`) et l'expiration ;
- les rôles du realm (`realm_access.roles`).

| Code | Cas |
|---|---|
| 401 | Jeton absent, illisible, mal signé, d'un autre émetteur, d'une autre audience ou expiré |
| 403 | Aucun des rôles demandés par la route, ou compte non rattaché à un client |
| 503 | Clés de Keycloak injoignables |

Les routes de données (mesures, consommation, prédictions, alertes, recommandations et économies) sont ouvertes aux rôles `CONSULT-SITE`, `CONSULT-CLIENT`, `GESTION-SITE` et `GESTION-CLIENT`. Le rôle `MONITORING` seul n'y donne pas accès.

**Cloisonnement par client** : chaque route de données ne renvoie que les sites du client de l'utilisateur (`app.site.id_client`, dépendance `ClientCourant` de `api/auth.py`). Le site d'un autre client se comporte comme un site inconnu (liste vide). Un administrateur EnerVision (`id_client` vide dans `app.utilisateur`) voit tous les clients. Le filtrage par site, pour les rôles `*-SITE`, viendra avec l'US6 (SMARTOPS-60).

**Protéger une nouvelle route** : ajouter la dépendance `exiger_role(...)` au routeur dans `main.py`, ou à la route pour récupérer l'utilisateur connecté :

```python
from api.auth import Utilisateur, exiger_role

GESTIONNAIRE = exiger_role("GESTION-SITE", "GESTION-CLIENT")


@router.post("/recommandations/{id}/decision")
def decider(utilisateur: Annotated[Utilisateur, Depends(GESTIONNAIRE)]):
    # utilisateur.id (sub Keycloak), utilisateur.id_client, utilisateur.roles
    ...
```

Le test `test_toutes_les_routes_api_exigent_un_jeton` échoue si une route `/api` est ouverte sans jeton.

**Entreprise de l'utilisateur** : le jeton ne dit pas à quelle entreprise (client) appartient l'utilisateur. L'API la lit dans `app.utilisateur`, grâce au `sub` du jeton. Cette ligne est écrite à la création du compte par l'API (`POST /api/utilisateurs`, SMARTOPS-84), qui rattache le nouveau compte à l'entreprise du gestionnaire qui le crée. L'API n'écrit jamais cette ligne à la connexion : un compte créé hors de l'API (par exemple dans la console Keycloak) reçoit un 403, car son entreprise est inconnue.

**Comptes de test** : se créent dans la console Keycloak (`http://localhost/auth/admin`), puis s'enregistrent dans `app.utilisateur` avec le même identifiant. Sans cette ligne, l'API refuse le compte (403). Marche à suivre : `infra/runner.md`, section « Créer un compte ».

**Tester dans Swagger** : récupérer un jeton depuis le front connecté (outils de développement du navigateur, en-tête `Authorization` d'un appel `/api`), puis le coller avec le bouton « Authorize ».

| Variable | Par défaut | Rôle |
|---|---|---|
| `KEYCLOAK_URL_INTERNE` | `http://keycloak:8080/auth` | Adresse de Keycloak sur le réseau Docker (lecture des clés). Sur la VM : `http://keycloak-<env>:8080/auth`, car le nom `keycloak` désigne aussi le Keycloak de l'autre environnement sur `traefik_public` |
| `KEYCLOAK_EMETTEUR` | `http://localhost/auth/realms/enervision` | Émetteur attendu dans les jetons |
| `KEYCLOAK_AUDIENCE` | `enervision-api` | Audience attendue |

### `GET /api/moi`

Utilisateur connecté, appelé par le front juste après la connexion. Ouvert à tout compte rattaché, quel que soit son rôle.

```json
{ "id": "8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10", "id_client": 1, "roles": ["CONSULT-SITE"] }
```

| Code | Cas |
|---|---|
| 200 | Jeton accepté, compte enregistré dans `app.utilisateur` (`id_client` null : administrateur EnerVision) |
| 401 | Jeton absent ou invalide |
| 403 | Compte absent de `app.utilisateur` : `{"detail": "Compte non rattaché à un client"}`, reconnu par le front |

### `GET /api/health`

| Code | Réponse | Cas |
|---|---|---|
| 200 | `{"status": "ok", "database": "ok"}` | API et base OK |
| 503 | `{"status": "degraded", "database": "unreachable"}` | PostgreSQL injoignable |

### `GET /api/sites/derniere-mesure`

Dernière mesure de chaque site (lue dans `gold.derniere_mesure`), avec le nom du site.

```json
[
  {
    "id_site": "SITE001",
    "nom": "Bureau Paris La Défense",
    "horodatage": "2026-10-21T14:30:00Z",
    "consommation_kw": 87.34,
    "data_quality": "good"
  }
]
```

`consommation_kw` vaut `null` si la mesure manque (capteur en panne).

### `GET /api/sites/{id_site}/consommation`

Consommation heure par heure d'un site (lue dans `gold.consommation_horaire`), en kWh et en euros.

| Paramètre | Obligatoire | Par défaut | Exemple |
|---|---|---|---|
| `debut` | non | `fin` moins 24 h | `2026-10-20T00:00:00Z` |
| `fin` | non | maintenant | `2026-10-21T00:00:00Z` |

```json
[
  { "heure": "2026-10-21T13:00:00Z", "consommation_kwh": 500.0, "cout_eur": 70.0 }
]
```

`cout_eur` = `consommation_kwh` × `PRIX_KWH_EUR` (variable du `.env`, tarif fixe provisoire de 0,14 € HT/kWh). Il vaut `null` si la consommation manque.

### `GET /api/sites/{id_site}/predictions`

Prévisions horaires d'un site (lues dans `gold.prediction`) pour les heures à venir : de l'heure pleine qui suit jusqu'à l'horizon demandé (24 ou 168 heures). Le modèle ajoute des lignes à chaque exécution : pour chaque heure, seule la prévision la plus récente est renvoyée.

| Paramètre | Obligatoire | Par défaut | Valeurs |
|---|---|---|---|
| `horizon` | non | `24h` | `24h`, `7j` |

```json
[
  {
    "heure": "2026-10-26T15:00:00Z",
    "consommation_kwh": 1790.0,
    "consommation_basse_kwh": 1700.0,
    "consommation_haute_kwh": 1870.0,
    "pic_prevu": true,
    "calculee_le": "2026-10-26T14:05:00Z",
    "version_modele": "rf-3"
  }
]
```

La fourchette (`consommation_basse_kwh`, `consommation_haute_kwh`) vaut `null` si le modèle n'en donne pas.

### `GET /api/alertes`

Alertes des sites actifs (lues dans `app.alerte_etat`), avec leur prise en compte. Les alertes en cours viennent d'abord, triées par gravité (`critical`, `high`, `medium`, `low`) puis de la plus récente à la plus ancienne. Avec `en_cours=false`, les alertes terminées suivent, de la plus récente à la plus ancienne : une vieille alerte critique ne cache pas les alertes récentes.

| Paramètre | Obligatoire | Par défaut | Rôle |
|---|---|---|---|
| `en_cours` | non | `true` | `false` inclut les alertes terminées |
| `id_site` | non | tous les sites | Alertes d'un seul site |
| `limite` | non | `100` | Nombre maximal d'alertes (1 à 500) |

```json
[
  {
    "id_alerte": 12,
    "id_site": "SITE002",
    "nom_site": "Usine Lyon Vénissieux",
    "source": "etl",
    "type": "spike",
    "severite": "critical",
    "message": "Pic à 1 150 kW",
    "debut": "2026-10-26T13:12:00Z",
    "fin": null,
    "valeur": 1150.0,
    "seuil": 1000.0,
    "prise_en_compte": true,
    "prise_par": "8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10",
    "prise_le": "2026-10-26T13:20:00Z"
  }
]
```

`fin` vaut `null` tant que l'alerte est en cours. `prise_par` est l'identifiant Keycloak de l'utilisateur qui l'a prise en compte.

### `GET /api/recommandations`

Recommandations des sites actifs (lues dans `app.recommandation_etat`), de la plus récente à la plus ancienne. `statut` est la dernière décision, ou `proposee` tant que personne n'a décidé.

| Paramètre | Obligatoire | Par défaut | Rôle |
|---|---|---|---|
| `id_site` | non | tous les sites | Recommandations d'un seul site |
| `statut` | non | tous | `proposee`, `acceptee` ou `refusee` |
| `limite` | non | `100` | Nombre maximal de recommandations (1 à 500) |

```json
[
  {
    "id_recommandation": 7,
    "id_site": "SITE002",
    "nom_site": "Usine Lyon Vénissieux",
    "id_alerte": 12,
    "regle": "decaler_production",
    "titre": "Décaler la ligne 2 après 20 h",
    "description": null,
    "date_creation": "2026-10-26T13:15:00Z",
    "gain_estime_eur": 380.0,
    "periode_gain": "unique",
    "statut": "acceptee",
    "decide_par": "8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10",
    "decide_le": "2026-10-26T13:30:00Z"
  }
]
```

`gain_estime_eur` et `periode_gain` (`unique` ou `semaine`) valent tous deux `null` si le gain n'est pas estimé.

### `GET /api/recommandations/economies`

Économies réalisées par site actif (lues dans `app.economies_realisees`) : somme des gains estimés des recommandations acceptées. Un site sans recommandation acceptée figure avec 0 €.

```json
[
  { "id_site": "SITE002", "nb_recommandations_acceptees": 2, "economies_eur": 500.0 }
]
```

Un gain par semaine n'est compté qu'une fois : `economies_eur` additionne des gains uniques et hebdomadaires.

## Lancer l'API

### Avec Docker Compose (depuis la racine du dépôt)

```bash
cp env.example .env
docker compose -f compose-local.yml up -d --build traefik db api
```

L'API n'est pas exposée directement : on y accède par Traefik, sur http://localhost/api.

### En local (Python 3.14)

Depuis la racine du dépôt :

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements-dev.txt
```

Lancer la base seule, puis l'API avec rechargement automatique :

```bash
docker compose -f compose-local.yml up -d db traefik keycloak
POSTGRES_HOST=localhost KEYCLOAK_URL_INTERNE=http://localhost/auth uvicorn api.main:app --reload
```

> `POSTGRES_HOST=localhost` remplace la valeur `db` du `.env`, qui n'existe que dans le réseau Docker. De même, `KEYCLOAK_URL_INTERNE=http://localhost/auth` fait lire les clés de Keycloak par Traefik, car `keycloak:8080` n'est joignable que dans le réseau Docker.

## Vérifications

Depuis la racine du dépôt (ce sont aussi les hooks pre-push) :

```bash
python -m pytest -q api
python -m mypy api common
ruff check api common
ruff format api common
```
