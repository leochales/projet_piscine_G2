# API métier (FastAPI)
# Contexte de build = racine du dépôt, pour embarquer common/ (code partagé)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/ ./api/
COPY common/ ./common/

# Dépendances installées seulement si requirements.txt existe
RUN if [ -f api/requirements.txt ]; then pip install --no-cache-dir -r api/requirements.txt; fi

EXPOSE 8000

# Lance l'API si api/main.py existe, sinon le conteneur attend (projet pas encore initialisé)
CMD ["sh", "-c", "if [ -f api/main.py ]; then exec uvicorn api.main:app --host 0.0.0.0 --port 8000; else echo 'api/main.py absent : API pas encore initialisée'; exec sleep infinity; fi"]
