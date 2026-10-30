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
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline, make_pipeline

from common.logs import configure_logging
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

logger = logging.getLogger(__name__)

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
        logger.warning(
            "sites sans heure mesurée dans l'entraînement, écartés : %s", inconnus
        )
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
    # Réentraînement hebdomadaire (model.reentrainement) : le modèle retenu fait mieux
    # que la version en production sur l'examen. None quand rien n'est comparé (premier
    # entraînement, ou aucune version en production).
    bat_production: bool | None = None

    @property
    def remplace_production(self) -> bool:
        """Le modèle est enregistré et prend l'alias production : il bat la référence
        sur la validation, et la version en production sur l'examen s'il y en a une."""
        return self.bat_reference and self.bat_production is not False


def entrainer_horizon(
    df: pd.DataFrame, moyennes: pd.Series, horizon: int, avec_test: bool = True
) -> Resultat:
    """Entraîne les deux modèles pour un horizon, choisit le meilleur sur la
    validation, puis le mesure une seule fois sur le test.

    Sans ``avec_test``, le test n'est ni calculé ni noté. Le réentraînement
    (``model.reentrainement``) mesure le modèle sur son propre examen : ces scores
    seraient calculés pour rien."""
    df = garder_sites_connus(df, moyennes)
    lignes = preparer(df, moyennes, horizon)
    noms = noms_variables(horizon, moyennes)
    refs = references(horizon)
    modeles = entrainer(lignes, noms)
    d = ajouter_previsions(lignes, modeles, noms, moyennes, "validation", horizon)
    validation = comparer(d, [*refs, *modeles])
    # Choix sur la validation seulement, d'après le WAPE (comme le seuil de la 30)
    meilleur = str(validation.loc[list(modeles), "WAPE_%"].idxmin())
    bat_reference = bool(
        validation.loc[meilleur, "WAPE_%"] < validation.loc[REFERENCE, "WAPE_%"]
    )
    if not avec_test:
        return Resultat(
            meilleur=meilleur,
            validation=validation,
            test=pd.DataFrame(columns=validation.columns),
            par_site=pd.DataFrame(),
            bat_reference=bat_reference,
            bat_reference_test=False,
            heures_test=0,
            variables_incompletes=0,
            sans_reference=0,
        )
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
        bat_reference=bat_reference,
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


def journaliser(horizon: int, r: Resultat) -> None:
    """Écrit le résultat d'un horizon dans les logs (``common.logs``), visibles dans
    Grafana. Le résumé est au niveau info, avec les scores en champs JSON. Les tableaux
    complets sont au niveau debug (``LOG_LEVEL=DEBUG``). Sans score de test (modèle
    refusé sur la validation au réentraînement), le résumé s'arrête à la validation."""
    wape_validation = float(r.validation.loc[r.meilleur, "WAPE_%"])
    champs = {
        "horizon": horizon,
        "modele_retenu": r.meilleur,
        "wape_validation": wape_validation,
        "wape_validation_reference": float(r.validation.loc[REFERENCE, "WAPE_%"]),
    }
    if r.test.empty:
        logger.info(
            "horizon %d h : modèle retenu %s, WAPE de %.2f %% sur la validation",
            horizon,
            r.meilleur,
            wape_validation,
            extra=champs,
        )
    else:
        wape_test = float(r.test.loc[r.meilleur, "WAPE_%"])
        champs["wape_test"] = wape_test
        champs["wape_test_reference"] = float(r.test.loc[REFERENCE, "WAPE_%"])
        if "production" in r.test.index:
            champs["wape_test_production"] = float(r.test.loc["production", "WAPE_%"])
        logger.info(
            "horizon %d h : modèle retenu %s, WAPE de %.2f %% sur la validation "
            "et de %.2f %% sur le test",
            horizon,
            r.meilleur,
            wape_validation,
            wape_test,
            extra=champs,
        )
        logger.info(
            "horizon %d h, test : %d heures mesurées, dont %d avec une variable "
            "manquante (prévues), %d sans référence (exclues de la comparaison)",
            horizon,
            r.heures_test,
            r.variables_incompletes,
            r.sans_reference,
        )
        logger.debug("horizon %d h, test :\n%s", horizon, r.test.round(2).to_string())
        logger.debug(
            "horizon %d h, WAPE %% par site sur le test :\n%s",
            horizon,
            r.par_site.round(2).to_string(),
        )
    logger.debug(
        "horizon %d h, validation :\n%s", horizon, r.validation.round(2).to_string()
    )
    if not r.bat_reference:
        logger.warning(
            "horizon %d h : %s ne fait pas mieux que %s sur la validation. "
            "Ce modèle ne sera pas enregistré.",
            horizon,
            r.meilleur,
            REFERENCE,
        )
    elif not r.bat_reference_test and not r.test.empty:
        logger.warning(
            "horizon %d h : %s bat %s sur la validation mais pas sur le test. "
            "À vérifier avant de l'utiliser.",
            horizon,
            r.meilleur,
            REFERENCE,
        )
    if r.bat_production is False:
        logger.info(
            "horizon %d h : %s ne fait pas mieux que la version en production sur "
            "l'examen, la version en production est gardée.",
            horizon,
            r.meilleur,
        )


def code_sortie(resultats: list[Resultat]) -> int:
    """Code de sortie de la commande : 1 si, pour un horizon, le modèle ne fait pas
    mieux que la référence (règle de SMARTOPS-30), 0 sinon. Quand l'entraînement tourne
    seul dans Docker, personne ne lit la console : un code non nul fait échouer le job,
    et l'erreur est visible dans les logs.

    Ne pas faire mieux que la version en production n'est pas une erreur : cette version
    est simplement gardée."""
    en_echec = [
        horizon for horizon, r in zip(HORIZONS, resultats) if not r.bat_reference
    ]
    if en_echec:
        logger.error(
            "aucun modèle ne fait mieux que la référence %s pour l'horizon %s h",
            REFERENCE,
            ", ".join(str(h) for h in en_echec),
        )
        return 1
    return 0


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
        journaliser(horizon, r)
        if empreinte is None:
            continue
        # Importé ici : sans MLflow, le reste du module n'en a pas besoin
        from model import registre

        final = (
            entrainer_modele_final(df, horizon, r.meilleur)
            if r.remplace_production
            else None
        )
        version = registre.enregistrer(
            r,
            horizon,
            REGLAGES[r.meilleur],
            empreinte,
            final,
            fin_donnees=df["heure"].max(),
        )
        if version:
            logger.info(
                "enregistré dans MLflow : %s, version %s (alias %s)",
                registre.nom_modele(horizon),
                version,
                registre.ALIAS,
            )
        else:
            logger.info(
                "horizon %d h : run enregistré dans MLflow, sans nouvelle version "
                "du modèle",
                horizon,
            )
    return resultats


if __name__ == "__main__":
    configure_logging("model")
    raise SystemExit(code_sortie(main()))
