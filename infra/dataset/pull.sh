#!/usr/bin/env bash
# Récupère data/raw (suivi par DVC, voir data/raw.dvc) sur la VM, depuis la racine du dépôt.
# Lancé par deploy.yml et dataset.yml sur le runner auto-hébergé.
#
# Le remote « vm » du dépôt passe par SSH (postes des développeurs). Sur la VM, le stockage
# est sur le même disque : son adresse est remplacée par le dossier, dans .dvc/config.local
# (jamais commité).
set -euo pipefail

store="${DVC_STORE:-/srv/enervision-dvc}"
version="3.67.1"
venv="$HOME/.venvs/dvc"

if [ ! -x "$venv/bin/dvc" ] || [ "$("$venv/bin/dvc" --version)" != "$version" ]; then
    python3 -m venv "$venv"
    "$venv/bin/pip" install --quiet "dvc==$version"
fi

"$venv/bin/dvc" config --local core.analytics false
"$venv/bin/dvc" remote modify --local vm url "$store"
"$venv/bin/dvc" pull data/raw.dvc
