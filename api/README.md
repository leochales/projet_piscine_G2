# API EnerVision

### Documentation

Avec Docker Compose, l'API passe par Traefik (http://localhost) ; lancée en local avec uvicorn, elle est sur http://localhost:8000.

| URL (Docker) | URL (uvicorn) | Contenu |
|---|---|---|
| http://localhost/api/docs | http://localhost:8000/api/docs | Swagger UI (tester les routes) |
| http://localhost/api/openapi.json | http://localhost:8000/api/openapi.json | Schéma OpenAPI |

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

Les routes de données (mesures, consommation) sont ouvertes aux rôles `CONSULT-SITE`, `CONSULT-CLIENT`, `GESTION-SITE` et `GESTION-CLIENT`. Le rôle `MONITORING` seul n'y donne pas accès.

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
