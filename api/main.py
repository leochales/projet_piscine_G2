"""Point d'entrée de l'API métier EnerVision."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from api.auth import REPONSES_AUTH, ROLES_METIER, exiger_role
from api.routers import alertes, health, mesures, predictions, recommandations
from api.routers.parametres import REPONSE_PARAMETRES, refuser_parametres_inconnus
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
# Sur chaque route, un paramètre de requête inconnu est refusé (422) ; vérifié après le
# jeton, pour qu'une requête sans jeton reçoive toujours 401.
REFUS_PARAMETRES = Depends(refuser_parametres_inconnus)

app.include_router(
    health.router,
    prefix=API_PREFIX,
    dependencies=[REFUS_PARAMETRES],
    responses=REPONSE_PARAMETRES,
)
# Données du dashboard, en lecture : ouvertes aux 4 rôles métier (pas à MONITORING seul)
for routeur in (mesures, predictions, alertes, recommandations):
    app.include_router(
        routeur.router,
        prefix=API_PREFIX,
        dependencies=[Depends(exiger_role(*ROLES_METIER)), REFUS_PARAMETRES],
        responses=REPONSES_AUTH | REPONSE_PARAMETRES,
    )

# Métriques Prometheus sur /metrics, hors de /api : Traefik ne les expose pas,
# seul Prometheus les lit par le réseau Docker. Absent de Swagger et de Schemathesis.
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
    app, include_in_schema=False
)
