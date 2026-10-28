"""Enregistrement des modèles de prévision dans MLflow (SMARTOPS-32).

Chaque entraînement crée un run par horizon dans l'expérience ``EXPERIENCE`` :
paramètres, scores de validation et de test (modèle et références), empreinte du jeu.
Si le modèle bat la référence sur la validation, il est enregistré comme nouvelle
version du modèle ``prevision-conso-24h`` ou ``prevision-conso-168h``, avec les
moyennes par site, et cette version reçoit l'alias ``production``. Sinon, le run reste
pour la trace, sans nouvelle version.

La génération des prévisions (SMARTOPS-33) charge la version ``production`` avec
``charger``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cloudpickle
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import sklearn
from mlflow import MlflowClient

if TYPE_CHECKING:
    from model.entrainement import Resultat

EXPERIENCE = "prevision-consommation"
ALIAS = "production"
# Moyennes par site, enregistrées dans le run avec le modèle : elles servent à
# normaliser la consommation et de liste des sites du modèle
MOYENNES = "moyennes_par_site.json"


def nom_modele(horizon: int) -> str:
    """Nom du modèle enregistré pour un horizon, que SMARTOPS-33 charge."""
    return f"prevision-conso-{horizon}h"


def metriques(tableau: pd.DataFrame, jeu: str) -> dict[str, float]:
    """Scores d'un tableau (une ligne par prévision) sous forme de métriques MLflow,
    par exemple ``validation_random_forest_WAPE``. MLflow refuse « % » dans un nom."""
    return {
        f"{jeu}_{prevision}_{score.removesuffix('_%')}": float(valeur)
        for prevision, ligne in tableau.iterrows()
        for score, valeur in ligne.items()
    }


def description(resultat: Resultat) -> str:
    """Explique d'où viennent les scores du run, et quel modèle est enregistré : les
    deux ne sont pas entraînés sur les mêmes données."""
    texte = (
        f"Scores : {resultat.meilleur} entraîné sur le jeu d'entraînement, choisi sur "
        "la validation et mesuré une seule fois sur le test. "
    )
    if resultat.bat_reference:
        texte += (
            "Modèle enregistré : le même, réentraîné sur toutes les données "
            "(entraînement, validation et test)."
        )
        if not resultat.bat_reference_test:
            texte += " ATTENTION : il ne bat pas la référence sur le test."
        return texte
    return texte + (
        "Aucun modèle enregistré : il ne bat pas la référence sur la validation."
    )


def enregistrer(
    resultat: Resultat,
    horizon: int,
    reglages: dict[str, Any],
    empreinte: str,
    final: tuple[Any, pd.Series] | None,
) -> str | None:
    """Crée le run MLflow d'un horizon. Si le modèle bat la référence sur la
    validation, enregistre le modèle final (réentraîné sur toutes les données) et ses
    moyennes par site, et place l'alias ``production`` sur la nouvelle version.
    Renvoie le numéro de cette version, ou None si aucune version n'est créée."""
    mlflow.set_experiment(EXPERIENCE)
    with mlflow.start_run(run_name=f"prevision-{horizon}h"):
        mlflow.log_params(
            {
                "horizon": horizon,
                "modele": resultat.meilleur,
                "empreinte_jeu": empreinte,
                **{f"reglage_{cle}": valeur for cle, valeur in reglages.items()},
            }
        )
        mlflow.log_metrics(
            metriques(resultat.validation, "validation")
            | metriques(resultat.test, "test")
        )
        mlflow.set_tag("bat_reference", str(resultat.bat_reference).lower())
        mlflow.set_tag("bat_reference_test", str(resultat.bat_reference_test).lower())
        # Description du run, affichée par l'interface de MLflow
        mlflow.set_tag("mlflow.note.content", description(resultat))
        if not resultat.bat_reference or final is None:
            return None
        modele, moyennes = final
        mlflow.log_dict({site: float(m) for site, m in moyennes.items()}, MOYENNES)
        info = mlflow.sklearn.log_model(
            modele,
            name="modele",
            registered_model_name=nom_modele(horizon),
            # Format par défaut de MLflow 3 : skops, qui demande une dépendance de plus.
            # cloudpickle (déjà installé avec MLflow) exécute du code au chargement :
            # acceptable ici, on ne charge que nos propres modèles, depuis notre MLflow.
            serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
            # Versions exactes de l'entraînement, plutôt qu'une détection automatique
            pip_requirements=[
                f"scikit-learn=={sklearn.__version__}",
                f"pandas=={pd.__version__}",
                f"numpy=={np.__version__}",
                f"cloudpickle=={cloudpickle.__version__}",
            ],
        )
    version = str(info.registered_model_version)
    MlflowClient().set_registered_model_alias(nom_modele(horizon), ALIAS, version)
    return version


@dataclass
class ModeleProduction:
    """Version ``production`` d'un horizon, telle que la prévision l'utilise."""

    modele: Any
    # Normalisation de la consommation et liste des sites du modèle
    moyennes: pd.Series
    # Nom et numéro de la version, par exemple « prevision-conso-24h/3 » : écrit dans
    # gold.prediction (version_modele) pour savoir quelle version a prévu chaque heure
    version: str


def charger(horizon: int) -> ModeleProduction:
    """Modèle de la version ``production`` d'un horizon, et ses moyennes par site."""
    nom = nom_modele(horizon)
    # Version lue une seule fois : modèle et moyennes viennent de la même version,
    # même si l'alias change pendant le chargement
    version = MlflowClient().get_model_version_by_alias(nom, ALIAS)
    modele = mlflow.sklearn.load_model(f"models:/{nom}/{version.version}")
    moyennes = mlflow.artifacts.load_dict(f"runs:/{version.run_id}/{MOYENNES}")
    return ModeleProduction(
        modele, pd.Series(moyennes, dtype=float), f"{nom}/{version.version}"
    )
