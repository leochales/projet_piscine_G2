"""Résume les rapports ZAP (baseline.json et api.json) en tableaux Markdown.

Utilisé par le job zap de deploy.yml pour afficher les alertes dans le résumé du workflow :
    python infra/ci/zap_summary.py "$ZAP_DIR" .zap/rules.tsv >> "$GITHUB_STEP_SUMMARY"

Chaque alerte porte l'action de .zap/rules.tsv (WARN si l'id n'y figure pas), pour que
celui qui trie voie ce qui est déjà réglé.
"""

import json
import sys
from pathlib import Path

RISQUES = {"3": "High", "2": "Medium", "1": "Low", "0": "Info"}
RAPPORTS = (("baseline", "Front (baseline)"), ("api", "API (authentifiée)"))
ACTION_PAR_DEFAUT = "WARN"
# FAIL d'abord, IGNORE en dernier : ce qui reste à trier est en haut du tableau
ORDRE_ACTIONS = {"FAIL": 0, "WARN": 1, "IGNORE": 2}


def lire_regles(chemin: Path) -> dict[str, str]:
    """Action (IGNORE, WARN ou FAIL) de chaque id de règle de rules.tsv."""
    regles: dict[str, str] = {}
    if not chemin.exists():
        return regles
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip() or ligne.startswith("#"):
            continue
        champs = ligne.split("\t")
        if len(champs) >= 2:
            regles[champs[0].strip()] = champs[1].strip().upper()
    return regles


def lire_alertes(rapport: Path) -> list[dict] | None:
    """Alertes du rapport, ou None s'il est absent ou illisible (JSON tronqué par exemple)."""
    try:
        contenu = json.loads(rapport.read_text(encoding="utf-8"))
        return [
            alerte
            for site in contenu.get("site", [])
            for alerte in site.get("alerts", [])
        ]
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def lignes_du_journal(journal: Path) -> list[str]:
    """Dernières lignes « Total of … URLs » et « FAIL-NEW … » du journal de ZAP."""
    if not journal.exists():
        return []
    lignes = [
        ligne.strip()
        for ligne in journal.read_text(encoding="utf-8", errors="replace").splitlines()
    ]
    retenues = []
    for debut in ("Total of", "FAIL-NEW"):
        trouvees = [ligne for ligne in lignes if ligne.startswith(debut)]
        if trouvees:
            retenues.append(f"`{trouvees[-1]}`")
    return retenues


def num_risque(alerte: dict) -> int:
    try:
        return int(alerte.get("riskcode", 0))
    except (TypeError, ValueError):
        return 0


def tableau(alertes: list[dict], regles: dict[str, str]) -> list[str]:
    avec_action = [
        (regles.get(str(a.get("pluginid")), ACTION_PAR_DEFAUT), a) for a in alertes
    ]
    avec_action.sort(key=lambda x: (ORDRE_ACTIONS.get(x[0], 1), -num_risque(x[1])))
    nb_ignorees = sum(1 for action, _ in avec_action if action == "IGNORE")
    lignes = [
        f"À trier : {len(avec_action) - nb_ignorees}. Déjà ignorées dans rules.tsv : {nb_ignorees}.",
        "",
        "| Id | Alerte | Risque | Règle | Instances |",
        "|---|---|---|---|--:|",
    ]
    for action, alerte in avec_action:
        nom = (alerte.get("name") or alerte.get("alert") or "").replace("|", "/")
        risque = RISQUES.get(str(alerte.get("riskcode")), "?")
        lignes.append(
            f"| {alerte.get('pluginid')} | {nom} | {risque} | {action} | {alerte.get('count', '')} |"
        )
    return lignes


def resume(dossier: Path, regles: dict[str, str]) -> str:
    sortie = ["## Résultats ZAP (dev)"]
    for nom, titre in RAPPORTS:
        sortie += ["", f"### {titre}"]
        alertes = lire_alertes(dossier / f"{nom}.json")
        if alertes is None:
            # Les commandes ::warning:: sont lues sur la sortie d'erreur, pas dans le résumé
            print(f"::warning::{nom}.json absent ou illisible", file=sys.stderr)
            sortie.append(
                "Rapport absent ou illisible : ZAP n'a pas fini d'écrire, voir les logs du job."
            )
            continue
        sortie += lignes_du_journal(dossier / f"{nom}.log")
        if not alertes:
            sortie.append("Aucune alerte.")
            continue
        sortie += [""] + tableau(alertes, regles)
    return "\n".join(sortie)


def main() -> int:
    dossier = Path(sys.argv[1])
    regles = lire_regles(Path(sys.argv[2]))
    print(resume(dossier, regles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
