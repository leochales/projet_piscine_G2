"""Entraînement du modèle de prévision (SMARTOPS-31).

Entraîne Ridge et random forest sur le jeu du ticket 93, pour les deux horizons
(24 h et 7 jours), les compare sur la validation avec la prévision de référence,
et garde le meilleur de chaque horizon.

    python -m model.entrainement
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge

from model.baseline import (
    BASELINES,
    ajouter_baselines,
    charger,
    chemin_par_defaut,
    scores,
)
from model.features import (
    HORIZONS,
    construire_variables,
    moyennes_par_site,
    noms_variables,
)


def preparer(df: pd.DataFrame, moyennes: pd.Series, horizon: int) -> pd.DataFrame:
    """Variables et cible de chaque ligne utilisable pour apprendre ou évaluer :
    consommation mesurée et toutes les variables connues."""
    variables = construire_variables(df, moyennes, horizon)
    noms = noms_variables(horizon, moyennes)
    # conso_norm est vide quand l'heure n'a pas été mesurée (taux_couverture = 0)
    mesuree = variables["conso_norm"].notna()
    # Ridge ne gère pas les cases vides : on garde les lignes où tout est connu
    complete = variables[noms].notna().all(axis=1)
    return variables[mesuree & complete]


def creer_modeles() -> dict[str, Ridge | RandomForestRegressor]:
    """Les deux modèles comparés, avec des réglages simples."""
    return {
        "ridge": Ridge(alpha=1.0),
        "random_forest": RandomForestRegressor(
            n_estimators=100,  # nombre d'arbres
            min_samples_leaf=5,  # au moins 5 lignes par feuille, contre le surapprentissage
            n_jobs=-1,  # utilise tous les cœurs du processeur
            random_state=0,  # même résultat à chaque lancement
        ),
    }


def entrainer(
    lignes: pd.DataFrame, noms: list[str]
) -> dict[str, Ridge | RandomForestRegressor]:
    """Entraîne chaque modèle sur les lignes du jeu d'entraînement."""
    train = lignes[lignes["jeu"] == "entrainement"]
    modeles = creer_modeles()
    for modele in modeles.values():
        modele.fit(train[noms], train["conso_norm"])
    return modeles


def prevoir_kwh(
    modele: Ridge | RandomForestRegressor,
    lignes: pd.DataFrame,
    noms: list[str],
    moyennes: pd.Series,
) -> pd.Series:
    """Prévision en kWh : le modèle prévoit conso_norm, qu'on remultiplie par la
    moyenne du site."""
    norm = pd.Series(modele.predict(lignes[noms]), index=lignes.index)
    return norm * lignes["id_site"].map(moyennes)


def comparer(
    lignes: pd.DataFrame,
    modeles: dict[str, Ridge | RandomForestRegressor],
    noms: list[str],
    moyennes: pd.Series,
    jeu: str = "validation",
) -> pd.DataFrame:
    """Scores des modèles et des prévisions de référence sur un jeu, une ligne par
    prévision. Toutes sont mesurées sur les mêmes heures."""
    d = lignes[lignes["jeu"] == jeu]
    # Mêmes heures pour tout le monde : celles où la référence existe aussi
    d = d.dropna(subset=list(BASELINES)).copy()
    for nom, modele in modeles.items():
        d[nom] = prevoir_kwh(modele, d, noms, moyennes)
    previsions = [*BASELINES, *modeles]
    return pd.DataFrame({nom: scores(d, nom) for nom in previsions}).T


def entrainer_horizon(
    df: pd.DataFrame, moyennes: pd.Series, horizon: int
) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Entraîne les deux modèles pour un horizon, choisit le meilleur sur la
    validation, puis le mesure une seule fois sur le test."""
    lignes = preparer(df, moyennes, horizon)
    noms = noms_variables(horizon, moyennes)
    modeles = entrainer(lignes, noms)
    validation = comparer(lignes, modeles, noms, moyennes, "validation")
    # Choix sur la validation seulement, d'après le WAPE (comme le seuil de la 30)
    meilleur = validation.loc[list(modeles), "WAPE_%"].idxmin()
    test = comparer(lignes, {meilleur: modeles[meilleur]}, noms, moyennes, "test")
    return meilleur, validation, test


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chemin", type=Path, default=chemin_par_defaut())
    args = parser.parse_args(argv)

    df = ajouter_baselines(charger(args.chemin))
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    for horizon in HORIZONS:
        meilleur, validation, test = entrainer_horizon(df, moyennes, horizon)
        print(f"===== horizon {horizon} h")
        print("validation :")
        print(validation.round(2))
        print(f"modèle retenu : {meilleur}")
        print("test :")
        print(test.round(2))


if __name__ == "__main__":
    main()
