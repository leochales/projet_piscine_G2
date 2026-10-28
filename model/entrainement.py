"""Entraînement du modèle de prévision (SMARTOPS-31).

Entraîne Ridge et random forest sur le jeu du ticket 93, pour les deux horizons
(24 h et 7 jours), les compare sur la validation avec la prévision de référence,
choisit le meilleur de chaque horizon et le mesure une seule fois sur le test.

S'il fait mieux que la référence sur la validation, le modèle retenu est réentraîné
sur toutes les données et enregistré dans MLflow (SMARTOPS-32, ``model.registre``).

    python -m model.entrainement [--chemin data/processed/dataset.parquet] [--sans-mlflow]

Sans ``MLFLOW_TRACKING_URI`` ni ``--sans-mlflow``, la commande s'arrête, comme
``model.dataset`` : MLflow écrirait sinon dans un dossier ``mlruns`` local.
"""

from __future__ import annotations

import argparse
import json
import os
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

# Référence retenue : la seule valable aux deux horizons. Une version du modèle
# n'est gardée que si elle fait mieux qu'elle (SMARTOPS-30)
REFERENCE = "baseline_semaine"

# Réglages des deux modèles, enregistrés avec le run MLflow
REGLAGES: dict[str, dict[str, float | int]] = {
    "ridge": {"alpha": 1.0},
    "random_forest": {
        "n_estimators": 100,  # nombre d'arbres
        # Au moins 50 lignes par feuille : modèle 10 fois plus léger qu'avec 5
        # (12 Mo au lieu de 124), pour un WAPE de validation égal ou meilleur
        "min_samples_leaf": 50,
    },
}


def references(horizon: int) -> list[str]:
    """Prévisions de référence valables pour un horizon : celles connues au moment de
    prévoir. À 7 jours, la veille n'est pas encore connue."""
    return [nom for nom, decalage in BASELINES.items() if decalage >= horizon]


def garder_sites_connus(df: pd.DataFrame, moyennes: pd.Series) -> pd.DataFrame:
    """Écarte, en le signalant, les sites sans moyenne d'entraînement (aucune heure
    mesurée avant la date de coupure, par exemple un site mis en service après) :
    le modèle ne peut pas les prévoir, mais ils ne doivent pas bloquer les autres."""
    inconnus = sorted(set(df["id_site"]) - set(moyennes.index))
    if inconnus:
        print(f"Sites sans heure mesurée dans l'entraînement, écartés : {inconnus}")
    return df[df["id_site"].isin(moyennes.index)]


def preparer(df: pd.DataFrame, moyennes: pd.Series, horizon: int) -> pd.DataFrame:
    """Variables et cible des heures mesurées, les seules qui servent à apprendre et
    à évaluer. Une heure dont une variable manque (un lag pendant une panne, par
    exemple) est gardée : les modèles savent la prévoir, comme en production."""
    variables = construire_variables(df, moyennes, horizon)
    # conso_norm est vide quand l'heure n'a pas été mesurée (taux_couverture = 0)
    return variables[variables["conso_norm"].notna()]


def creer_modeles() -> dict[str, Modele]:
    """Les deux modèles comparés, avec des réglages simples (``REGLAGES``)."""
    return {
        # Ridge ne calcule pas avec une case vide : elle est remplacée par la
        # moyenne de la colonne sur l'entraînement (autour de 1, la moyenne du site)
        "ridge": make_pipeline(
            SimpleImputer(strategy="mean", keep_empty_features=True),
            Ridge(**REGLAGES["ridge"]),
        ),
        # Le random forest de scikit-learn accepte les cases vides tel quel
        "random_forest": RandomForestRegressor(
            **REGLAGES["random_forest"],
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
    horizon: int,
) -> pd.DataFrame:
    """Lignes d'un jeu, avec une colonne de prévision par modèle. On ne garde que les
    heures où les références valables pour l'horizon existent : modèles et
    références sont notés sur les mêmes heures."""
    d = lignes[lignes["jeu"] == jeu].dropna(subset=references(horizon)).copy()
    for nom, modele in modeles.items():
        d[nom] = prevoir_kwh(modele, d, noms, moyennes)
    return d


def comparer(d: pd.DataFrame, previsions: list[str]) -> pd.DataFrame:
    """Scores de chaque prévision, une ligne par prévision."""
    return pd.DataFrame({nom: scores(d, nom) for nom in previsions}).T


def wape_par_site(d: pd.DataFrame, previsions: list[str]) -> pd.DataFrame:
    """WAPE de chaque prévision, site par site, avec le même calcul que la prévision
    de référence (model.baseline). Sert à vérifier les sites un par un : la règle de
    SMARTOPS-30 porte sur le score global."""
    return pd.DataFrame(
        {nom: d.groupby("id_site").apply(scores, nom)["WAPE_%"] for nom in previsions}
    )


@dataclass
class Resultat:
    """Résultat de l'entraînement pour un horizon."""

    meilleur: str
    validation: pd.DataFrame
    test: pd.DataFrame
    par_site: pd.DataFrame
    # Règle de SMARTOPS-30 : le modèle retenu fait mieux que la référence, en WAPE
    # global, sur la validation. Le modèle n'est enregistré que si c'est vrai. La
    # décision ne se prend pas sur le test, qui ne sert qu'au score affiché : sinon, en
    # relançant jusqu'à ce qu'un modèle passe, le test servirait plusieurs fois.
    bat_reference: bool
    # Information seulement : le modèle retenu fait aussi mieux que la référence sur
    # le test. S'il perd, il est quand même enregistré (la règle est sur la
    # validation), mais un avertissement le signale, en console et dans MLflow.
    bat_reference_test: bool
    # Heures mesurées du test : toutes, avec au moins une variable manquante
    # (prévues quand même), et sans référence (exclues de la comparaison)
    heures_test: int
    variables_incompletes: int
    sans_reference: int


def entrainer_horizon(df: pd.DataFrame, moyennes: pd.Series, horizon: int) -> Resultat:
    """Entraîne les deux modèles pour un horizon, choisit le meilleur sur la
    validation, puis le mesure une seule fois sur le test."""
    df = garder_sites_connus(df, moyennes)
    lignes = preparer(df, moyennes, horizon)
    noms = noms_variables(horizon, moyennes)
    refs = references(horizon)
    modeles = entrainer(lignes, noms)
    d = ajouter_previsions(lignes, modeles, noms, moyennes, "validation", horizon)
    validation = comparer(d, [*refs, *modeles])
    # Choix sur la validation seulement, d'après le WAPE (comme le seuil de la 30)
    meilleur = str(validation.loc[list(modeles), "WAPE_%"].idxmin())
    retenu = {meilleur: modeles[meilleur]}
    # Prévisions du test calculées une fois, pour les scores globaux et par site
    d = ajouter_previsions(lignes, retenu, noms, moyennes, "test", horizon)
    test = comparer(d, [*refs, meilleur])
    heures_test = lignes[lignes["jeu"] == "test"]
    return Resultat(
        meilleur=meilleur,
        validation=validation,
        test=test,
        par_site=wape_par_site(d, [REFERENCE, meilleur]),
        bat_reference=bool(
            validation.loc[meilleur, "WAPE_%"] < validation.loc[REFERENCE, "WAPE_%"]
        ),
        bat_reference_test=bool(
            test.loc[meilleur, "WAPE_%"] < test.loc[REFERENCE, "WAPE_%"]
        ),
        heures_test=len(heures_test),
        variables_incompletes=int(heures_test[noms].isna().any(axis=1).sum()),
        sans_reference=int(heures_test[refs].isna().any(axis=1).sum()),
    )


def entrainer_modele_final(
    df: pd.DataFrame, horizon: int, nom: str
) -> tuple[Modele, pd.Series]:
    """Réentraîne le modèle retenu sur toutes les données (entraînement, validation et
    test), une fois le choix fait et le score mesuré : le modèle de production
    profite ainsi des mois les plus récents. Les moyennes par site sont recalculées
    sur ces mêmes données, et renvoyées pour être enregistrées avec le modèle."""
    moyennes = moyennes_par_site(df)
    df = garder_sites_connus(df, moyennes)
    lignes = preparer(df, moyennes, horizon)
    noms = noms_variables(horizon, moyennes)
    modele = creer_modeles()[nom]
    modele.fit(lignes[noms], lignes["conso_norm"])
    return modele, moyennes


def lire_empreinte(chemin: Path) -> str | None:
    """Empreinte du jeu, écrite par model.dataset dans rapport_qualite.json, à côté du
    jeu. Elle relie le run MLflow au jeu d'entraînement utilisé. None si le rapport
    manque ou est illisible."""
    rapport = chemin.parent / "rapport_qualite.json"
    try:
        return str(json.loads(rapport.read_text(encoding="utf-8"))["empreinte"])
    except (OSError, KeyError, ValueError):
        return None


def afficher(horizon: int, r: Resultat) -> None:
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
    if not r.bat_reference:
        print(
            f"ATTENTION : {r.meilleur} ne fait pas mieux que {REFERENCE} sur la "
            "validation. Ce modèle ne sera pas enregistré."
        )
    elif not r.bat_reference_test:
        print(
            f"ATTENTION : {r.meilleur} bat {REFERENCE} sur la validation mais pas sur "
            "le test. Il sera enregistré : à vérifier avant de l'utiliser."
        )


def main(argv: list[str] | None = None) -> list[Resultat]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chemin", type=Path, default=chemin_par_defaut())
    parser.add_argument(
        "--sans-mlflow", action="store_true", help="ne rien enregistrer dans MLflow"
    )
    args = parser.parse_args(argv)
    # Sans adresse, MLflow écrirait dans un dossier mlruns local, sans prévenir
    if not args.sans_mlflow and not os.environ.get("MLFLOW_TRACKING_URI"):
        parser.error("MLFLOW_TRACKING_URI manquant (serveur MLflow), ou --sans-mlflow")
    # None avec --sans-mlflow : rien ne sera enregistré
    empreinte = None if args.sans_mlflow else lire_empreinte(args.chemin)
    # Sans empreinte, le modèle enregistré ne serait relié à aucun jeu
    if not args.sans_mlflow and empreinte is None:
        parser.error(
            "empreinte du jeu introuvable (rapport_qualite.json absent ou "
            "illisible à côté du jeu) : relancer model.dataset, ou --sans-mlflow"
        )

    df = ajouter_baselines(charger(args.chemin))
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    # Pas de filtre des sites ici : entrainer_horizon écarte ceux sans entraînement
    # pour l'évaluation, mais le modèle final apprend tous les sites, y compris ceux
    # mis en service après la date de coupure
    resultats = []
    for horizon in HORIZONS:
        r = entrainer_horizon(df, moyennes, horizon)
        resultats.append(r)
        afficher(horizon, r)
        if empreinte is None:
            continue
        # Importé ici : sans MLflow, le reste du module n'en a pas besoin
        from model import registre

        final = (
            entrainer_modele_final(df, horizon, r.meilleur) if r.bat_reference else None
        )
        version = registre.enregistrer(
            r, horizon, REGLAGES[r.meilleur], empreinte, final
        )
        if version:
            print(
                f"enregistré dans MLflow : {registre.nom_modele(horizon)}, "
                f"version {version} (alias {registre.ALIAS})"
            )
        else:
            print("run enregistré dans MLflow, sans nouvelle version du modèle")
    return resultats


if __name__ == "__main__":
    main()
