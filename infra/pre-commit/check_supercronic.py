"""Vérifie que le bloc supercronic est identique dans etl/Dockerfile et backup/Dockerfile.

Le binaire est téléchargé et vérifié (version, empreintes) dans chaque Dockerfile, pour
que chaque image se construise seule, sans dépendre d'une autre image ni d'un contexte
fourni par compose. Ce hook empêche les deux copies de diverger : une mise à jour de
supercronic se fait dans les deux fichiers à la fois.
"""

import sys
from pathlib import Path

DOCKERFILES = (Path("etl/Dockerfile"), Path("backup/Dockerfile"))
BEGIN = "# --- supercronic : début du bloc commun"
END = "# --- supercronic : fin du bloc commun"


def block(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(BEGIN)]
    ends = [i for i, line in enumerate(lines) if line.startswith(END)]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        sys.exit(f"{path} : marqueurs du bloc supercronic absents ou en double")
    return "\n".join(lines[starts[0] : ends[0] + 1])


def main() -> int:
    reference, *others = DOCKERFILES
    expected = block(reference)
    different = [str(path) for path in others if block(path) != expected]
    if different:
        print(
            f"Bloc supercronic différent de {reference} dans : {', '.join(different)}. "
            "Mettre à jour les deux fichiers de la même façon."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
