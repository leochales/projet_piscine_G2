"""Prévision de référence (SMARTOPS-30).

Lit le jeu d'entraînement du ticket 93 et mesure l'erreur de deux prévisions naïves :
la consommation de la veille et celle de la semaine précédente, à la même heure.
Une version du modèle n'est gardée que si elle fait mieux que ces scores.

    python -m model.baseline [--jeu test] [--chemin data/processed/dataset.parquet]

Le jeu est lu dans ``DATASET_OUTPUT_DIR`` (``data/processed`` par défaut), comme
``model.dataset`` l'écrit.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from model.dataset import DEFAULT_OUTPUT_DIR, SPLITS
from model.features import valeurs_passees

DATASET_NAME = "dataset.parquet"
# Décalage de chaque prévision, en heures
BASELINES = {"baseline_veille": 24, "baseline_semaine": 168}


def chemin_par_defaut() -> Path:
    """Chemin du jeu produit par ``model.dataset`` (dans Docker : /data/processed)."""
    dossier = Path(os.environ.get("DATASET_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    return dossier / DATASET_NAME


def charger(chemin: Path | None = None) -> pd.DataFrame:
    df = pd.read_parquet(chemin or chemin_par_defaut())
    return df.sort_values(["id_site", "heure"], ignore_index=True)


def ajouter_baselines(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute la valeur de la veille et de la semaine précédente, dans le temps (même
    calcul que les lags du modèle) : si l'heure passée manque, la prévision est vide."""
    df = df.copy()
    df[list(BASELINES)] = valeurs_passees(df, "moyenne_kw", BASELINES)
    return df


def scores(d: pd.DataFrame, colonne: str) -> pd.Series:
    """MAE, RMSE et WAPE, sur les heures mesurées qui ont une prévision."""
    d = d.dropna(subset=["consommation_kwh_brute", colonne])
    reel = d["consommation_kwh_brute"]
    mae = mean_absolute_error(reel, d[colonne])
    rmse = np.sqrt(mean_squared_error(reel, d[colonne]))
    return pd.Series({"MAE": mae, "RMSE": rmse, "WAPE_%": 100 * mae / reel.mean()})


def scores_reference(
    df: pd.DataFrame, jeu: str = "validation"
) -> dict[str, dict[str, float]]:
    """Scores de chaque prévision de référence sur un jeu, pour que l'entraînement
    compare ses modèles au même découpage. ``df`` : le jeu complet (les décalages
    sont calculés avant de garder ``jeu``, pour que ses premières heures aient une
    valeur passée)."""
    avec_baselines = ajouter_baselines(df)
    sous_jeu = avec_baselines[avec_baselines["jeu"] == jeu]
    return {
        nom: {k: float(v) for k, v in scores(sous_jeu, nom).items()}
        for nom in BASELINES
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chemin", type=Path, default=chemin_par_defaut())
    parser.add_argument("--jeu", choices=SPLITS, default="test")
    args = parser.parse_args(argv)

    df = ajouter_baselines(charger(args.chemin))
    sous_jeu = df[df["jeu"] == args.jeu]
    mesurees = sous_jeu["consommation_kwh_brute"].notna()
    for colonne in BASELINES:
        sans_prevision = int((mesurees & sous_jeu[colonne].isna()).sum())
        print(f"===== {colonne} (jeu {args.jeu})")
        print(f"heures mesurées sans valeur passée, exclues : {sans_prevision}")
        print(scores(sous_jeu, colonne).round(2))
        print(sous_jeu.groupby("id_site").apply(scores, colonne).round(2))


if __name__ == "__main__":
    main()
