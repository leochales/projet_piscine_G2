"""Point d'entrée de l'API métier EnerVision."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from api.routers import health
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

app.include_router(health.router, prefix=API_PREFIX)

# Métriques Prometheus sur /metrics, hors de /api : Traefik ne les expose pas,
# seul Prometheus les lit par le réseau Docker. Absent de Swagger et de Schemathesis.
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
    app, include_in_schema=False
)
