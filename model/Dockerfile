# Modèle de prévision : jeu d'entraînement (python -m model.dataset), entraînement
# (python -m model.entrainement), prévisions horaires (service prevision : cron
# supercronic, model/crontab) et réentraînement hebdomadaire (service reentrainement,
# model/crontab-reentrainement). Contexte de build = racine du dépôt, pour embarquer
# common/ (code partagé)

# --- supercronic : début du bloc commun aux Dockerfiles qui lancent un cron (etl, backup, model) ---
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
# --- supercronic : fin du bloc commun (vérifié par infra/pre-commit/check_supercronic.py) ---

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    GIT_PYTHON_REFRESH=quiet

COPY --from=supercronic /supercronic /usr/local/bin/supercronic

WORKDIR /app

COPY model/ ./model/
COPY common/ ./common/

RUN pip install --no-cache-dir -r model/requirements.txt \
    && pip uninstall -y pip

# Par défaut : le jeu d'entraînement (service dataset). Les services entrainement,
# prevision et reentrainement donnent leur propre commande dans compose
CMD ["python", "-m", "model.dataset"]
