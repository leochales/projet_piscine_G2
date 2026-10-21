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
