# Modèle de prévision : jeu d'entraînement (python -m model.dataset), puis entraînement
# et prévisions. Contexte de build = racine du dépôt, pour embarquer common/ (code partagé)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    GIT_PYTHON_REFRESH=quiet

WORKDIR /app

COPY model/ ./model/
COPY common/ ./common/

RUN pip install --no-cache-dir -r model/requirements.txt \
    && pip uninstall -y pip

CMD ["python", "-m", "model.dataset"]
