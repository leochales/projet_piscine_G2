"""Point d'entrée de l'API métier EnerVision."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from api.auth import REPONSES_AUTH, ROLES_METIER, exiger_role
from api.routers import health, mesures
from common.config import get_settings
from common.logs import configure_logging

configure_logging("api")

# Toutes les routes sont sous /api : Traefik transmet /api tel quel à ce service
API_PREFIX = "/api"

app = FastAPI(
    title="EnerVision API",
    description="API métier : sites, mesures, prédictions, alertes et recommandations.",
    version="0.1.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=None,
    openapi_url=f"{API_PREFIX}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().api_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api/health reste public : Docker, Traefik et la supervision l'appellent sans jeton.
# Tout autre routeur ajouté ici doit être protégé par exiger_role
# (test_auth.py vérifie qu'aucune route /api n'est ouverte par erreur).
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(
    mesures.router,
    prefix=API_PREFIX,
    dependencies=[Depends(exiger_role(*ROLES_METIER))],
    responses=REPONSES_AUTH,
)

# Métriques Prometheus sur /metrics, hors de /api : Traefik ne les expose pas,
# seul Prometheus les lit par le réseau Docker. Absent de Swagger et de Schemathesis.
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
    app, include_in_schema=False
)
