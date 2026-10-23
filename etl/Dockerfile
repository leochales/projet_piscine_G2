# ETL : script Python lancé par cron (supercronic, pensé pour les conteneurs)
# Contexte de build = racine du dépôt, pour embarquer common/ (code partagé)

# supercronic : cron sans démon, lit les variables d'environnement et logue sur stdout.
# ADD --checksum vérifie l'empreinte du binaire (release v0.2.50) sans apt ni curl.
# Une étape par architecture : --checksum ne peut pas être conditionnel.
FROM scratch AS supercronic-amd64
ADD --checksum=sha256:d2d7c97fbfefc763d5bbcbbb3f8d61f9dd3410ce5d05a737c414994b80b8cdd0 \
    --chmod=0755 \
    https://github.com/aptible/supercronic/releases/download/v0.2.50/supercronic-linux-amd64 /supercronic

FROM scratch AS supercronic-arm64
ADD --checksum=sha256:a1c0af9872e8de89a1ce5c1b596e26c42917d5a2cf914d98faee2e28156899e2 \
    --chmod=0755 \
    https://github.com/aptible/supercronic/releases/download/v0.2.50/supercronic-linux-arm64 /supercronic

# DL3006 : faux positif, c'est l'une de nos étapes ci-dessus, pas une image externe
# hadolint ignore=DL3006
FROM supercronic-${TARGETARCH:-amd64} AS supercronic

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ETL_ENABLED=true

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
CMD ["sh", "-c", "if [ \"$ETL_ENABLED\" = \"false\" ]; then echo 'ETL_ENABLED=false : ETL désactivé, aucun job lancé'; exec sleep infinity; fi; exec supercronic -passthrough-logs etl/crontab"]
