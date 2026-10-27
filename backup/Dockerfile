# Sauvegarde : pg_dump des bases, chiffré et envoyé par restic, lancé par cron (supercronic)
# Contexte de build = racine du dépôt, comme les autres images

# supercronic : repris de l'image de l'ETL, seul endroit où il est téléchargé et vérifié
# (version et empreintes dans etl/Dockerfile). « supercronic » est un contexte de build
# nommé, fourni par compose (additional_contexts: service:etl) : construire cette image
# avec docker compose build ou docker buildx bake, pas avec un docker build seul.

# restic compilé depuis ses sources : le binaire officiel 0.19.1 est construit avec
# Go 1.26.4 et des dépendances qui ont depuis des failles HIGH corrigées (Trivy).
# Recompilé avec un Go à jour, dépendances vulnérables montées à leur version corrigée.
# À simplifier (COPY --from=restic/restic) dès qu'une version officielle les intègre.
FROM golang:1.27.3-alpine3.23 AS restic
ADD --checksum=sha256:bb9b1a19040744d26d8a79be029d4e6b189c45ccc9d8831d7fe367d3c33df725 \
    https://github.com/restic/restic/releases/download/v0.19.1/restic-0.19.1.tar.gz /tmp/restic.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/restic.tar.gz --strip-components=1 \
    && go get \
        github.com/klauspost/compress@v1.18.7 \
        golang.org/x/crypto@v0.57.0 \
        golang.org/x/net@v0.60.0 \
        golang.org/x/text@v0.42.0 \
        google.golang.org/grpc@v1.83.2 \
    && go mod tidy \
    && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /usr/bin/restic ./cmd/restic \
    && /usr/bin/restic version

FROM alpine:3.23

# Client PostgreSQL de la même version majeure que le serveur (postgres:18) :
# pg_dump refuse de sauvegarder un serveur plus récent que lui.
# DL3018 : la version majeure est fixée par le nom du paquet (postgresql18) ; le
# correctif exact n'est pas épinglé pour récupérer les mises à jour de sécurité d'Alpine.
# Les certificats racines (HTTPS vers Azure) sont déjà dans l'image alpine.
# hadolint ignore=DL3018
RUN apk add --no-cache postgresql18-client \
    && adduser -D -u 1000 backup \
    && mkdir -p /home/backup/.cache/restic \
    && chown backup:backup /home/backup/.cache/restic

# DL3022 : supercronic est un contexte nommé fourni par compose (voir plus haut)
# hadolint ignore=DL3022
COPY --from=supercronic /usr/local/bin/supercronic /usr/local/bin/supercronic
COPY --from=restic /usr/bin/restic /usr/local/bin/restic

WORKDIR /app
# --chmod : le bit exécutable ne survit pas à un build lancé depuis Windows
COPY --chmod=0755 backup/backup.sh ./
COPY backup/crontab ./

# Les dumps ne passent jamais par le disque : pg_dump écrit directement dans restic
USER 1000:1000

# Planning : backup/crontab. -passthrough-logs : les lignes JSON de backup.sh
# sortent telles quelles, comme celles de l'ETL
CMD ["supercronic", "-passthrough-logs", "/app/crontab"]
