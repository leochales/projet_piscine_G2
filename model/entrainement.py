"""Entraînement du modèle de prévision (SMARTOPS-31).

Entraîne Ridge et random forest sur le jeu du ticket 93, pour les deux horizons
(24 h et 7 jours), les compare sur la validation avec la prévision de référence,
choisit le meilleur de chaque horizon et le mesure une seule fois sur le test.
L'enregistrement du modèle retenu dans MLflow est l'objet de SMARTOPS-32.

    python -m model.entrainement [--chemin data/processed/dataset.parquet]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline, make_pipeline

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

# Les deux sortes de modèles comparés
Modele: TypeAlias = Pipeline | RandomForestRegressor

# Référence retenue : la seule valable aux deux horizons (à 7 jours, la veille
# n'est pas encore connue)
REFERENCE = "baseline_semaine"


def preparer(df: pd.DataFrame, moyennes: pd.Series, horizon: int) -> pd.DataFrame:
    """Variables et cible des heures mesurées, les seules qui servent à apprendre et
    à évaluer. Une heure dont une variable manque (un lag pendant une panne, par
    exemple) est gardée : les modèles savent la prévoir, comme en production."""
    variables = construire_variables(df, moyennes, horizon)
    # conso_norm est vide quand l'heure n'a pas été mesurée (taux_couverture = 0)
    return variables[variables["conso_norm"].notna()]


def creer_modeles() -> dict[str, Modele]:
    """Les deux modèles comparés, avec des réglages simples."""
    return {
        # Ridge ne calcule pas avec une case vide : elle est remplacée par la
        # moyenne de la colonne sur l'entraînement (autour de 1, la moyenne du site)
        "ridge": make_pipeline(
            SimpleImputer(strategy="mean", keep_empty_features=True),
            Ridge(alpha=1.0),
        ),
        # Le random forest de scikit-learn accepte les cases vides tel quel
        "random_forest": RandomForestRegressor(
            n_estimators=100,  # nombre d'arbres
            min_samples_leaf=5,  # au moins 5 lignes par feuille (surapprentissage)
            n_jobs=-1,  # utilise tous les cœurs du processeur
            random_state=0,  # même résultat à chaque lancement
        ),
    }


def entrainer(lignes: pd.DataFrame, noms: list[str]) -> dict[str, Modele]:
    """Entraîne chaque modèle sur les lignes du jeu d'entraînement seulement."""
    train = lignes[lignes["jeu"] == "entrainement"]
    modeles = creer_modeles()
    for modele in modeles.values():
        modele.fit(train[noms], train["conso_norm"])
    return modeles


def prevoir_kwh(
    modele: Modele, lignes: pd.DataFrame, noms: list[str], moyennes: pd.Series
) -> pd.Series:
    """Prévision en kWh : le modèle prévoit conso_norm, qu'on remultiplie par la
    moyenne du site."""
    norm = pd.Series(modele.predict(lignes[noms]), index=lignes.index)
    return norm * lignes["id_site"].map(moyennes)


def ajouter_previsions(
    lignes: pd.DataFrame,
    modeles: dict[str, Modele],
    noms: list[str],
    moyennes: pd.Series,
    jeu: str,
) -> pd.DataFrame:
    """Lignes d'un jeu, avec une colonne de prévision par modèle. On ne garde que les
    heures où la référence existe : modèles et référence sont notés sur les mêmes
    heures."""
    d = lignes[lignes["jeu"] == jeu].dropna(subset=list(BASELINES)).copy()
    for nom, modele in modeles.items():
        d[nom] = prevoir_kwh(modele, d, noms, moyennes)
    return d


def comparer(
    lignes: pd.DataFrame,
    modeles: dict[str, Modele],
    noms: list[str],
    moyennes: pd.Series,
    jeu: str = "validation",
) -> pd.DataFrame:
    """Scores des modèles et des prévisions de référence sur un jeu, une ligne par
    prévision, sur les mêmes heures."""
    d = ajouter_previsions(lignes, modeles, noms, moyennes, jeu)
    previsions = [*BASELINES, *modeles]
    return pd.DataFrame({nom: scores(d, nom) for nom in previsions}).T


def wape_par_site(
    lignes: pd.DataFrame,
    modeles: dict[str, Modele],
    noms: list[str],
    moyennes: pd.Series,
    jeu: str = "test",
) -> pd.DataFrame:
    """WAPE de la référence retenue et de chaque modèle, site par site : le modèle
    doit faire mieux sur chaque site, pas seulement en moyenne."""
    d = ajouter_previsions(lignes, modeles, noms, moyennes, jeu)
    sites = dict(list(d.groupby("id_site")))
    return pd.DataFrame(
        {
            nom: {site: scores(g, nom)["WAPE_%"] for site, g in sites.items()}
            for nom in [REFERENCE, *modeles]
        }
    )


@dataclass
class Resultat:
    """Résultat de l'entraînement pour un horizon."""

    meilleur: str
    validation: pd.DataFrame
    test: pd.DataFrame
    par_site: pd.DataFrame
    # Heures mesurées du test : toutes, avec au moins une variable manquante
    # (prévues quand même), et sans référence (exclues de la comparaison)
    heures_test: int
    variables_incompletes: int
    sans_reference: int


def entrainer_horizon(df: pd.DataFrame, moyennes: pd.Series, horizon: int) -> Resultat:
    """Entraîne les deux modèles pour un horizon, choisit le meilleur sur la
    validation, puis le mesure une seule fois sur le test."""
    lignes = preparer(df, moyennes, horizon)
    noms = noms_variables(horizon, moyennes)
    modeles = entrainer(lignes, noms)
    validation = comparer(lignes, modeles, noms, moyennes, "validation")
    # Choix sur la validation seulement, d'après le WAPE (comme le seuil de la 30)
    meilleur = str(validation.loc[list(modeles), "WAPE_%"].idxmin())
    retenu = {meilleur: modeles[meilleur]}
    test = lignes[lignes["jeu"] == "test"]
    return Resultat(
        meilleur=meilleur,
        validation=validation,
        test=comparer(lignes, retenu, noms, moyennes, "test"),
        par_site=wape_par_site(lignes, retenu, noms, moyennes, "test"),
        heures_test=len(test),
        variables_incompletes=int(test[noms].isna().any(axis=1).sum()),
        sans_reference=int(test[list(BASELINES)].isna().any(axis=1).sum()),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chemin", type=Path, default=chemin_par_defaut())
    args = parser.parse_args(argv)

    df = ajouter_baselines(charger(args.chemin))
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    for horizon in HORIZONS:
        r = entrainer_horizon(df, moyennes, horizon)
        print(f"===== horizon {horizon} h")
        print("validation :")
        print(r.validation.round(2))
        print(f"modèle retenu : {r.meilleur}")
        print(
            f"test : {r.heures_test} heures mesurées, dont "
            f"{r.variables_incompletes} avec une variable manquante (prévues), "
            f"{r.sans_reference} sans référence (exclues de la comparaison)"
        )
        print(r.test.round(2))
        print("WAPE % par site sur le test :")
        print(r.par_site.round(2))


if __name__ == "__main__":
    main()
