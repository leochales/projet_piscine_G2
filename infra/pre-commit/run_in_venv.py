"""Lance Python avec les dépendances du projet, que le .venv soit activé ou non.

Utilisé par les hooks pre-commit (pytest, mypy) : sans ce script, un push depuis
un éditeur ou un terminal sans venv activé échoue avec « python not found ».

Ordre de recherche :
1. le .venv à la racine du dépôt (macOS / Linux et Windows) ;
2. sinon le python du PATH, hors environnement de pre-commit (cas de la CI).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

VENV_PYTHONS = (Path(".venv/bin/python"), Path(".venv/Scripts/python.exe"))


def find_python() -> str:
    for python in VENV_PYTHONS:
        if python.exists():
            return str(python)

    # pre-commit place son propre environnement (sans pytest ni mypy) en tête du PATH.
    # normcase + normpath : sous Windows, la casse et les séparateurs peuvent différer.
    def normalize(p: str) -> str:
        return os.path.normcase(os.path.normpath(p))

    hook_env = normalize(str(Path(sys.executable).parent))
    path = os.pathsep.join(
        p
        for p in os.environ["PATH"].split(os.pathsep)
        if p and normalize(p) != hook_env
    )
    python = shutil.which("python", path=path) or shutil.which("python3", path=path)
    if python is None:
        sys.exit("Python introuvable : créer le .venv à la racine (voir api/README.md)")
    return python


if __name__ == "__main__":
    sys.exit(subprocess.call([find_python(), *sys.argv[1:]]))
