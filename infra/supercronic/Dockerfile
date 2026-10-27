# supercronic : cron sans démon, lit les variables d'environnement et logue sur stdout.
# Seul endroit où il est téléchargé : les images etl et backup le copient depuis cette
# étape, fournie comme contexte de build nommé (additional_contexts: service:supercronic
# dans les fichiers compose). Image de construction seulement, jamais démarrée.
#
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
FROM supercronic-${TARGETARCH:-amd64}
