# API métier (FastAPI)
# Contexte de build = racine du dépôt, pour embarquer common/ (code partagé)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/ ./api/
COPY common/ ./common/

# Dépendances installées seulement si requirements.txt existe
RUN if [ -f api/requirements.txt ]; then pip install --no-cache-dir -r api/requirements.txt; fi \
    && pip uninstall -y pip

EXPOSE 8000

# Lance l'API si api/main.py existe, sinon le conteneur attend (projet pas encore initialisé)
#   --forwarded-allow-ips="*" : uvicorn croit les en-têtes X-Forwarded-* de Traefik, et
#     construit ses redirections en https:// derrière le TLS de Traefik. Sans risque : l'API
#     n'est joignable que par le réseau Docker de Traefik.
#   --no-server-header : pas d'en-tête « Server: uvicorn »
CMD ["sh", "-c", "if [ -f api/main.py ]; then exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips='*' --no-server-header; else echo 'api/main.py absent : API pas encore initialisée'; exec sleep infinity; fi"]
