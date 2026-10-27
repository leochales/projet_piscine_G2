"""Vérifie que le bloc supercronic est identique dans tous les Dockerfiles qui l'ont.

Le binaire est téléchargé et vérifié (version, empreintes) dans chaque Dockerfile, pour
que chaque image se construise seule, sans dépendre d'une autre image ni d'un contexte
fourni par compose. Ce hook empêche les copies de diverger : une mise à jour de
supercronic se fait dans tous les fichiers à la fois. Tout Dockerfile du dépôt qui
contient les marqueurs du bloc est vérifié, une nouvelle image comprise.
"""

import os
import sys
from pathlib import Path

BEGIN = "# --- supercronic : début du bloc commun"
END = "# --- supercronic : fin du bloc commun"
# Dossiers sans Dockerfile du projet, parfois très gros : non parcourus
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".terraform"}


def dockerfiles() -> list[Path]:
    """Dockerfiles du dépôt (Dockerfile, Dockerfile.*, *.Dockerfile)."""
    found = []
    for directory, subdirs, files in os.walk("."):
        subdirs[:] = [d for d in subdirs if d not in IGNORED_DIRS]
        found += [Path(directory, name) for name in files if "Dockerfile" in name]
    return sorted(found)


def block(path: Path) -> str | None:
    """Le bloc entre les marqueurs, ou None si le fichier n'en a pas."""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(BEGIN)]
    ends = [i for i, line in enumerate(lines) if line.startswith(END)]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        sys.exit(f"{path} : marqueurs du bloc supercronic incomplets ou en double")
    return "\n".join(lines[starts[0] : ends[0] + 1])


def main() -> int:
    blocks = {path: b for path in dockerfiles() if (b := block(path)) is not None}
    if not blocks:
        return 0
    reference, expected = next(iter(blocks.items()))
    different = [str(path) for path, b in blocks.items() if b != expected]
    if different:
        print(
            f"Bloc supercronic différent de {reference} dans : {', '.join(different)}. "
            "Mettre à jour tous les fichiers de la même façon."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
