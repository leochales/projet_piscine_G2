"""Prévision de référence (SMARTOPS-30).

Lit le jeu d'entraînement du ticket 93 et mesure, sur le jeu de test, l'erreur
de deux prévisions naïves : la consommation de la veille et celle de la semaine
précédente, à la même heure.

    python -m model.baseline
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

DATASET = Path("data/processed/dataset.parquet")
BASELINES = {"baseline_veille": 24, "baseline_semaine": 168}


def charger(chemin=DATASET):
    df = pd.read_parquet(chemin)
    return df.sort_values(["id_site", "heure"], ignore_index=True)


def ajouter_baselines(df):
    df = df.copy()
    par_site = df.groupby("id_site")["moyenne_kw"]
    for nom, decalage in BASELINES.items():
        df[nom] = par_site.shift(decalage)
    return df


def scores(d, colonne):
    d = d.dropna(subset=["consommation_kwh_brute", colonne])
    reel = d["consommation_kwh_brute"]
    mae = mean_absolute_error(reel, d[colonne])
    rmse = np.sqrt(mean_squared_error(reel, d[colonne]))
    return pd.Series({"MAE": mae, "RMSE": rmse, "WAPE_%": 100 * mae / reel.mean()})


if __name__ == "__main__":
    df = ajouter_baselines(charger())
    test = df[df["jeu"] == "test"]
    for colonne in BASELINES:
        print("=====", colonne)
        print(scores(test, colonne).round(2))
        print(test.groupby("id_site").apply(scores, colonne).round(2))
