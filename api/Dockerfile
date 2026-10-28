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
#   En-têtes X-Forwarded-* ignorés (uvicorn ne les croit que de 127.0.0.1) : tout conteneur
#     de traefik_public, autre environnement compris, pourrait les forger. L'API n'en a pas
#     besoin : elle ne redirige pas (redirect_slashes=False) et n'utilise pas l'IP du client.
#   --no-server-header : pas d'en-tête « Server: uvicorn »
CMD ["sh", "-c", "if [ -f api/main.py ]; then exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --no-server-header; else echo 'api/main.py absent : API pas encore initialisée'; exec sleep infinity; fi"]
