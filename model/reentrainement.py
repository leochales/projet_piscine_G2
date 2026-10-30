"""Réentraînement hebdomadaire du modèle de prévision (SMARTOPS-34).

    python -m model.reentrainement [--chemin data/processed/dataset.parquet]

Le service ``reentrainement`` le lance chaque semaine (``model/crontab-reentrainement``).

Le jeu réunit l'historique CSV (``model.dataset``) et les heures de
``gold.consommation_horaire`` plus récentes que le CSV, mesurées sur au moins 80 % de
leurs minutes. Ce sont ces mesures récentes qui
apportent du neuf. Relancer l'entraînement sur le seul CSV redonnerait le même modèle.

Les 7 derniers jours du jeu servent d'examen (le jeu ``test`` de ``model.entrainement``).
Pour chaque horizon :

1. la méthode (Ridge ou random forest) est choisie sur la validation, comme à
   l'entraînement (``model.entrainement``) ;
2. un candidat est entraîné avec cette méthode sur tout ce qui précède l'examen ;
3. le candidat, la version ``production`` et la prévision de référence sont notés sur
   les mêmes heures de l'examen, les mêmes sites ;
4. la nouvelle version est enregistrée, et l'alias ``production`` bouge, seulement si le
   candidat bat la référence (règle de SMARTOPS-30) et la version en production (WAPE
   plus bas). Elle est alors réentraînée sur toutes les données, examen compris.

La commande se termine en erreur (code 1) si le modèle ne fait pas mieux que la référence.
Sans assez de mesures dans gold, elle prévient dans les logs et ne réentraîne rien.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import replace
from pathlib import Path

import pandas as pd
from mlflow.exceptions import MlflowException
from sqlalchemy import Connection, text

from common.db import get_engine
from common.logs import configure_logging
from model import registre
from model.baseline import ajouter_baselines, charger, chemin_par_defaut
from model.dataset import GOLD_COLUMNS, SPLIT_RATIOS
from model.entrainement import (
    REFERENCE,
    REGLAGES,
    Resultat,
    code_sortie,
    comparer,
    entrainer_horizon,
    entrainer_modele_final,
    journaliser,
    lire_empreinte,
    references,
    wape_par_site,
)
from model.features import (
    COUVERTURE_MIN_MOYENNE,
    HISTORIQUE_UTILE,
    HORIZONS,
    conso_mesuree,
    construire_variables,
    moyennes_par_site,
    noms_variables,
)
from model.prevision import SANS_VERSION

logger = logging.getLogger(__name__)

UNE_HEURE = pd.Timedelta(hours=1)

# Les 7 derniers jours du jeu : l'examen qui départage le candidat et la production
EXAMEN = pd.Timedelta(days=7)

# Avant l'examen, même proportion entre entraînement et validation que dans le jeu CSV
# (70 % et 15 % du jeu entier)
PART_ENTRAINEMENT = SPLIT_RATIOS[0] / sum(SPLIT_RATIOS)

# Mesures de gold nécessaires : les 7 jours de l'examen, plus les 7 jours d'avant. La
# référence d'une heure est la même heure la semaine précédente. Sans cette semaine
# d'avant, elle tomberait dans le trou entre la fin du CSV et gold, et l'examen ne
# porterait en pratique que sur quelques jours.
GOLD_MIN = 2 * EXAMEN

# Part minimale des minutes mesurées pour qu'une heure de gold compte, comme pour les pics
# de model.prevision. Une heure avec une seule minute mesurée n'est pas une valeur
# d'entraînement ni d'examen fiable. heure_complete ne suffit pas : il dit seulement que
# l'heure est terminée.
COUVERTURE_MIN_HEURE = COUVERTURE_MIN_MOYENNE

# Heures notées en dessous desquelles la comparaison avec la production ne veut rien
# dire (une semaine complète de 7 sites en compte plus de 1 000)
MIN_HEURES_EXAMEN = 100


def lire_gold(conn: Connection) -> pd.DataFrame:
    """Heures de ``gold.consommation_horaire`` mesurées sur au moins
    ``COUVERTURE_MIN_HEURE`` de leurs minutes, au format du jeu CSV.

    Les autres sont écartées, comme des heures absentes de gold : le jeu les remplit de
    cases vides, que le modèle sait prévoir et que la référence exclut. Une heure
    terminée n'est pas forcément mesurée : une panne de capteur laisse une heure sans
    mesure, ou avec une seule minute."""
    lignes = conn.execute(
        text(
            """
            SELECT id_site, heure, consommation_kwh, pic_kw, moyenne_kw, nb_mesures,
                   nb_imputees, taux_couverture, heure_complete
            FROM gold.consommation_horaire
            WHERE heure_complete
            """
        )
    ).all()
    df = pd.DataFrame(lignes, columns=GOLD_COLUMNS)
    # NUMERIC arrive en Decimal, et l'heure dans le fuseau de la session PostgreSQL
    for colonne in ("consommation_kwh", "pic_kw", "moyenne_kw", "taux_couverture"):
        df[colonne] = df[colonne].astype(float)
    df["heure"] = pd.to_datetime(df["heure"], utc=True)
    df = df[df["taux_couverture"] >= COUVERTURE_MIN_HEURE].copy()
    # Comme dans le jeu CSV, sur une heure les kW moyens valent des kWh
    df["consommation_kwh_brute"] = conso_mesuree(df)
    df["methode_imputation"] = "none"
    return df


def fusionner(csv: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    """Le jeu CSV, suivi des heures de gold plus récentes que sa dernière heure. Une
    heure ne peut ainsi jamais être en double."""
    gold = gold[gold["heure"] > csv["heure"].max()].copy()
    gold["heure"] = gold["heure"].astype(csv["heure"].dtype)
    df = pd.concat([csv.drop(columns="jeu"), gold], ignore_index=True)
    return df.sort_values(["id_site", "heure"], ignore_index=True)


def decouper(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute la colonne ``jeu``. Les 7 derniers jours sont l'examen, appelé ``test`` pour
    réutiliser ``model.entrainement``. Ce qui précède est coupé en deux, dans le temps,
    entre entraînement et validation. Le découpage se fait sur des heures communes à tous
    les sites, jamais ligne par ligne."""
    heures = df["heure"].drop_duplicates().sort_values(ignore_index=True)
    debut_examen = heures.iloc[-1] - EXAMEN
    avant = heures[heures <= debut_examen].reset_index(drop=True)
    debut_validation = avant.iloc[int(len(avant) * PART_ENTRAINEMENT)]
    df = df.copy()
    df["jeu"] = "validation"
    df.loc[df["heure"] < debut_validation, "jeu"] = "entrainement"
    df.loc[df["heure"] > debut_examen, "jeu"] = "test"
    return df


def heures_examen(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Heures mesurées de l'examen dont les références valables pour l'horizon existent,
    comme dans ``model.entrainement`` : tout le monde est noté sur les mêmes heures."""
    colonnes = ["consommation_kwh_brute", *references(horizon)]
    examen = df[df["jeu"] == "test"].dropna(subset=colonnes)
    return examen[["id_site", "heure", *colonnes]]


def prevoir_examen(
    df: pd.DataFrame,
    modele: object,
    moyennes: pd.Series,
    horizon: int,
    examen: pd.DataFrame,
) -> pd.Series:
    """Prévision en kWh d'un modèle pour les heures de l'examen, avec ses propres
    moyennes par site. Renvoie une série au même index que ``examen``. Un site inconnu du
    modèle n'est pas prévu : la série ne le contient pas."""
    connus = examen[examen["id_site"].isin(moyennes.index)]
    if connus.empty:
        return pd.Series(dtype=float)
    # Les variables remontent au plus à HISTORIQUE_UTILE avant l'heure prévue
    depuis = connus["heure"].min() - HISTORIQUE_UTILE
    sous = df[df["id_site"].isin(moyennes.index) & (df["heure"] >= depuis)]
    variables = construire_variables(sous, moyennes, horizon)
    cles = connus[["id_site", "heure"]].rename_axis("ligne").reset_index()
    variables = cles.merge(variables, on=["id_site", "heure"], how="left")
    norm = modele.predict(variables[noms_variables(horizon, moyennes)])
    kwh = norm * variables["id_site"].map(moyennes)
    return pd.Series(kwh.to_numpy(), index=variables["ligne"])


def charger_production(horizon: int) -> registre.ModeleProduction | None:
    """Version ``production`` d'un horizon, ou None si aucune n'est enregistrée."""
    try:
        return registre.charger(horizon)
    except MlflowException as erreur:
        if erreur.error_code not in SANS_VERSION:
            raise
        logger.warning(
            "pas de version %s du modèle %s : rien à comparer",
            registre.ALIAS,
            registre.nom_modele(horizon),
        )
        return None


def evaluer_sur_l_examen(df: pd.DataFrame, r: Resultat, horizon: int) -> Resultat:
    """Mesure le candidat sur l'examen : ``r`` reçoit les scores de l'examen. Le candidat
    (la méthode retenue, entraînée sur tout ce qui précède l'examen), la version en
    production et les références sont notés sur les mêmes heures, et seulement sur les
    sites que le candidat et la production connaissent.

    Les heures que la version en production a vues à son entraînement
    (``registre.fin_des_donnees``) ne sont pas notées : sans cela, un réentraînement
    relancé dans la semaine la favoriserait.

    Renvoie ``r`` avec ``bat_production`` :

    - None sans version en production. Il n'y a rien à comparer : le modèle est
      enregistré s'il bat la référence, même si l'examen est trop court pour être noté.
    - faux si le candidat ne fait pas mieux que la production, ou si l'examen est trop
      court pour les comparer. La production est alors gardée."""
    candidat, moyennes = entrainer_modele_final(
        df[df["jeu"] != "test"], horizon, r.meilleur
    )
    production = charger_production(horizon)
    sites = set(moyennes.index)
    fin = None
    if production is not None:
        sites &= set(production.moyennes.index)
        # Sans run connu (version fabriquée à la main), aucune heure n'est écartée
        if production.run_id:
            fin = registre.fin_des_donnees(production.run_id)
    examen = df[(df["jeu"] == "test") & df["id_site"].isin(sites)]
    if fin is not None:
        deja_vues = examen.loc[examen["heure"] <= fin, "heure"].nunique()
        if deja_vues:
            logger.info(
                "horizon %d h : %d heures de l'examen sont avant la fin des données "
                "de la version en production (%s), elles ne sont pas notées",
                horizon,
                deja_vues,
                fin,
            )
        examen = examen[examen["heure"] > fin]
    # Heures mesurées des sites notés, avant d'écarter celles sans référence
    mesurees = int(conso_mesuree(examen).notna().sum())
    examen = heures_examen(examen, horizon)
    if len(examen) < MIN_HEURES_EXAMEN:
        logger.warning(
            "horizon %d h : %d heures notées sur l'examen, il en faut au moins %d "
            "pour comparer le candidat à la version en production",
            horizon,
            len(examen),
            MIN_HEURES_EXAMEN,
        )
        return replace(r, bat_production=None if production is None else False)

    d = examen.copy()
    d[r.meilleur] = prevoir_examen(df, candidat, moyennes, horizon, examen)
    previsions = [*references(horizon), r.meilleur]
    if production is not None:
        d["production"] = prevoir_examen(
            df, production.modele, production.moyennes, horizon, examen
        )
        previsions.append("production")
    test = comparer(d, previsions)
    wape = test["WAPE_%"]
    return replace(
        r,
        test=test,
        par_site=wape_par_site(d, [REFERENCE, r.meilleur]),
        bat_reference_test=bool(wape[r.meilleur] < wape[REFERENCE]),
        bat_production=(
            None if production is None else bool(wape[r.meilleur] < wape["production"])
        ),
        heures_test=mesurees,
        sans_reference=mesurees - len(d),
    )


def reentrainer_horizon(df: pd.DataFrame, horizon: int, empreinte: str) -> Resultat:
    """Réentraîne un horizon, et enregistre le modèle s'il remplace la production."""
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    # Sans test : les scores viennent de l'examen, mesuré seulement pour un modèle qui
    # bat la référence sur la validation (inutile de le comparer à la production sinon)
    r = entrainer_horizon(df, moyennes, horizon, avec_test=False)
    if r.bat_reference:
        r = evaluer_sur_l_examen(df, r, horizon)
    journaliser(horizon, r)
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
            "horizon %d h : %s, version %s en production (alias %s)",
            horizon,
            registre.nom_modele(horizon),
            version,
            registre.ALIAS,
        )
    else:
        logger.info(
            "horizon %d h : pas de nouvelle version, la version en production est gardée",
            horizon,
        )
    return r


def reentrainer(
    csv: pd.DataFrame, gold: pd.DataFrame, empreinte_csv: str
) -> list[Resultat]:
    """Réentraîne les deux horizons sur le CSV et gold. Renvoie un résultat par horizon,
    ou rien s'il n'y a pas assez de mesures dans gold."""
    recent = gold[gold["heure"] > csv["heure"].max()]
    couverture = (
        recent["heure"].max() - recent["heure"].min() + UNE_HEURE
        if not recent.empty
        else pd.Timedelta(0)
    )
    if couverture < GOLD_MIN:
        logger.warning(
            "gold ne couvre que %s d'heures complètes récentes, il en faut au moins %s : "
            "aucun réentraînement",
            couverture,
            GOLD_MIN,
        )
        return []
    df = fusionner(csv, gold)
    df = ajouter_baselines(decouper(df))
    examen = df.loc[df["jeu"] == "test", "heure"]
    logger.info(
        "jeu du réentraînement : %d heures de gold après le CSV, examen du %s au %s",
        recent["heure"].nunique(),
        examen.min(),
        examen.max(),
    )
    # Le run MLflow garde de quelles données vient le modèle
    empreinte = f"{empreinte_csv}+gold:{df['heure'].max():%Y-%m-%dT%H}"
    return [reentrainer_horizon(df, horizon, empreinte) for horizon in HORIZONS]


def main(argv: list[str] | None = None) -> list[Resultat]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chemin", type=Path, default=chemin_par_defaut())
    args = parser.parse_args(argv)
    # Sans adresse, MLflow écrirait dans un dossier mlruns local, sans prévenir
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        parser.error("MLFLOW_TRACKING_URI manquant (serveur MLflow)")
    empreinte = lire_empreinte(args.chemin)
    # Sans empreinte, le modèle enregistré ne serait relié à aucun jeu
    if empreinte is None:
        parser.error(
            "empreinte du jeu introuvable (rapport_qualite.json absent ou illisible "
            "à côté du jeu) : relancer model.dataset"
        )
    with get_engine().connect() as conn:
        gold = lire_gold(conn)
    return reentrainer(charger(args.chemin), gold, empreinte)


if __name__ == "__main__":
    configure_logging("model")
    raise SystemExit(code_sortie(main()))
