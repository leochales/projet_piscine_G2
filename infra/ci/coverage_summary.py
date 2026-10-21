"""Convertit le résumé de couverture de vitest (coverage-summary.json) en tableau Markdown.

Utilisé par la CI pour afficher la couverture du front dans le résumé du workflow :
    python infra/ci/coverage_summary.py front/coverage/coverage-summary.json
"""

import json
import sys
from pathlib import Path

THRESHOLD = 80  # même seuil que front/vitest.config.ts
METRICS = ("lines", "statements", "functions", "branches")


def cell(pct: float) -> str:
    icon = "✅" if pct >= THRESHOLD else "❌"
    return f"{icon} {pct:g} %"


def display_path(path: Path, root: Path) -> Path:
    """Chemin relatif à front/ si possible, sinon tel quel (le tableau ne doit jamais planter)."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def to_markdown(summary: dict[str, dict[str, dict[str, float]]], root: Path) -> str:
    header = "| Fichier | Lignes | Instructions | Fonctions | Branches |"
    rows = [header, "|---|--:|--:|--:|--:|"]
    for path, data in sorted(summary.items()):
        if path == "total":
            continue
        name = display_path(Path(path), root)
        rows.append(
            f"| `{name}` | " + " | ".join(cell(data[m]["pct"]) for m in METRICS) + " |"
        )
    total = summary["total"]
    rows.append(
        "| **Total** | "
        + " | ".join(f"**{cell(total[m]['pct'])}**" for m in METRICS)
        + " |"
    )
    return "\n".join(rows)


def main() -> int:
    report = Path(sys.argv[1])
    if not report.exists():
        print("Pas de données (tests du front non lancés).")
        return 0
    summary = json.loads(report.read_text(encoding="utf-8"))
    # Les chemins du rapport sont absolus : on les affiche par rapport au dossier front/
    root = report.resolve().parent.parent
    print(to_markdown(summary, root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
