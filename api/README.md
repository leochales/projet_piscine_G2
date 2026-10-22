# API EnerVision

### Documentation

Avec Docker Compose, l'API passe par Traefik (http://localhost) ; lancée en local avec uvicorn, elle est sur http://localhost:8000.

| URL (Docker) | URL (uvicorn) | Contenu |
|---|---|---|
| http://localhost/api/docs | http://localhost:8000/api/docs | Swagger UI (tester les routes) |
| http://localhost/api/openapi.json | http://localhost:8000/api/openapi.json | Schéma OpenAPI |

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
docker compose -f compose-local.yml up -d db
POSTGRES_HOST=localhost uvicorn api.main:app --reload
```

> `POSTGRES_HOST=localhost` remplace la valeur `db` du `.env`, qui n'existe que dans le réseau Docker.

## Vérifications

Depuis la racine du dépôt (ce sont aussi les hooks pre-push) :

```bash
python -m pytest -q api
python -m mypy api common
ruff check api common
ruff format api common
```
