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


def valeur_passee(df: pd.DataFrame, heures: int) -> pd.Series:
    """``moyenne_kw`` du même site, ``heures`` heures plus tôt.

    Le décalage se fait sur l'heure, pas sur le numéro de ligne : si l'heure passée
    manque (trou dans gold.consommation_horaire), la valeur est vide au lieu d'être
    prise sur une autre heure."""
    passe = df[["id_site", "heure", "moyenne_kw"]].copy()
    passe["heure"] = passe["heure"] + pd.Timedelta(hours=heures)
    valeurs = df[["id_site", "heure"]].merge(
        passe, on=["id_site", "heure"], how="left", validate="many_to_one"
    )["moyenne_kw"]
    # merge renumérote les lignes : on garde l'index de df
    return pd.Series(valeurs.to_numpy(), index=df.index, name=f"moins_{heures}h")


def ajouter_baselines(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for nom, decalage in BASELINES.items():
        df[nom] = valeur_passee(df, decalage)
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
