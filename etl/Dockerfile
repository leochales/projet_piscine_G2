# ETL : script Python lancé par cron (supercronic, pensé pour les conteneurs)
# Contexte de build = racine du dépôt, pour embarquer common/ (code partagé)

# supercronic : téléchargé et vérifié dans infra/supercronic/Dockerfile, fourni ici comme
# contexte de build nommé (additional_contexts: service:supercronic dans les fichiers
# compose). Construire avec docker compose build ou docker buildx bake.

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ETL_ENABLED=true

# DL3022 : supercronic est un contexte nommé fourni par compose (voir plus haut)
# hadolint ignore=DL3022
COPY --from=supercronic /supercronic /usr/local/bin/supercronic

WORKDIR /app

COPY etl/ ./etl/
COPY common/ ./common/

# Dépendances installées seulement si requirements.txt existe
RUN if [ -f etl/requirements.txt ]; then pip install --no-cache-dir -r etl/requirements.txt; fi \
    && pip uninstall -y pip

# Planning : etl/crontab (modifiable sans toucher à ce Dockerfile)
# ETL_ENABLED=false : le conteneur reste démarré mais n'exécute aucun job
# -passthrough-logs : les lignes JSON des jobs (common/logs.py) sortent telles
# quelles, sans être enveloppées par supercronic (qui les classerait toutes en info)
# Amorçage des sites pas encore amorcés (etl/bootstrap.py) lancé en arrière-plan,
# en même temps que le cron : il ne retarde pas la collecte, sa durée est
# bornée, et supercronic devient tout de suite le PID 1 (arrêt propre).
CMD ["sh", "-c", "if [ \"$ETL_ENABLED\" = \"false\" ]; then echo 'ETL_ENABLED=false : ETL désactivé, aucun job lancé'; exec sleep infinity; fi; python -m etl.bootstrap & exec supercronic -passthrough-logs etl/crontab"]
