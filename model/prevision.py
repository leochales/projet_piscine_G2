"""Prévisions de consommation des sites dans gold.prediction (SMARTOPS-33).

Lancé chaque heure (``model/crontab``, service ``prevision``). Pour chaque site actif,
prévoit les heures à venir, de l'heure pleine qui suit jusqu'à 7 jours, avec les
versions ``production`` des modèles enregistrés dans MLflow (``model.registre``) :

  - le modèle 24 h prévoit les 24 premières heures ;
  - le modèle 7 jours (168 h) prévoit les heures suivantes, jusqu'à 168. Si le modèle
    24 h n'a pas de version en production, il prévoit aussi les 24 premières.

Chaque heure a ainsi une seule prévision par exécution, celle du modèle le plus précis
disponible, et ``version_modele`` dit lequel. L'API lit la plus récente de chaque heure
(api/routers/predictions.py).

La consommation est lue dans ``gold.consommation_horaire``, sur ``HISTORIQUE_UTILE``.
Un site sans mesure à l'heure en cours (capteur en panne, par exemple) ou inconnu du
modèle est écarté avec un avertissement : les autres sont prévus quand même.

Fourchette : centiles 10 et 90 des prévisions des arbres du random forest. Un modèle
Ridge n'en donne pas (bornes NULL). ``pic_prevu`` reste faux : le pic de l'heure n'est
pas encore prévu (SMARTOPS-95).

Avec ``MODELE_CACHE_DIR`` (volume ``modele_cache`` du service), chaque version est
téléchargée une seule fois : ensuite, MLflow ne sert qu'à lire le numéro de la version
``production``, et le modèle est lu sur le disque.

    python -m model.prevision
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import (
    INVALID_PARAMETER_VALUE,
    RESOURCE_DOES_NOT_EXIST,
    ErrorCode,
)
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import Connection, text

from common.db import get_engine
from common.logs import configure_logging
from model import registre
from model.features import (
    HISTORIQUE_UTILE,
    HORIZONS,
    ajouter_heures_a_prevoir,
    construire_variables,
    derniere_mesure_par_site,
    noms_variables,
    sites_en_retard,
)

logger = logging.getLogger(__name__)

# Fourchette : part des arbres du random forest sous la borne basse, et sous la haute
CENTILE_BAS = 10
CENTILE_HAUT = 90
UNE_HEURE = pd.Timedelta(hours=1)
# Codes de MLflow pour un modèle ou un alias absent (selon le stockage de MLflow). Une
# autre erreur (serveur injoignable) arrête le job : elle n'est pas « pas de modèle »
SANS_VERSION = {
    ErrorCode.Name(RESOURCE_DOES_NOT_EXIST),
    ErrorCode.Name(INVALID_PARAMETER_VALUE),
}
# Colonnes écrites dans gold.prediction (calculee_le et pic_prevu : valeurs par défaut)
COLONNES = [
    "id_site",
    "heure_prevue",
    "consommation_prevue_kwh",
    "consommation_basse_kwh",
    "consommation_haute_kwh",
    "version_modele",
]


def debut_des_previsions(maintenant: datetime) -> pd.Timestamp:
    """Première heure à prévoir : l'heure pleine qui suit, comme la fenêtre de l'API
    (``calculer_fenetre``). L'heure en cours est déjà entamée. Une heure sans fuseau
    est lue comme de l'UTC, comme ailleurs dans le projet."""
    maintenant = pd.Timestamp(maintenant)
    if maintenant.tzinfo is None:
        maintenant = maintenant.tz_localize(UTC)
    return maintenant.tz_convert(UTC).floor("h") + UNE_HEURE


def lire_historique(conn: Connection, debut: pd.Timestamp) -> pd.DataFrame:
    """Consommation horaire des sites actifs sur l'historique utile, heure en cours
    comprise (l'ETL la met à jour chaque minute)."""
    lignes = conn.execute(
        text(
            """
            SELECT c.id_site, c.heure, c.moyenne_kw, c.taux_couverture
            FROM gold.consommation_horaire AS c
            JOIN app.site AS s ON s.id_site = c.id_site
            WHERE s.statut = 'active' AND c.heure >= :depuis AND c.heure < :debut
            """
        ),
        {"depuis": debut - HISTORIQUE_UTILE, "debut": debut},
    ).all()
    df = pd.DataFrame(
        lignes, columns=["id_site", "heure", "moyenne_kw", "taux_couverture"]
    )
    # NUMERIC arrive en Decimal, et l'heure dans le fuseau de la session PostgreSQL
    return df.assign(
        heure=pd.to_datetime(df["heure"], utc=True),
        moyenne_kw=df["moyenne_kw"].astype(float),
        taux_couverture=df["taux_couverture"].astype(float),
    )


def sites_prevus(
    historique: pd.DataFrame, production: registre.ModeleProduction, debut: pd.Timestamp
) -> pd.DataFrame:
    """Historique des sites que le modèle peut prévoir. Écarte, avec un avertissement
    qui nomme la version, les sites inconnus du modèle (à réentraîner) et ceux sans
    mesure à l'heure qui précède ``debut`` (``ajouter_heures_a_prevoir`` les
    refuserait tous)."""
    moyennes = production.moyennes
    inconnus = sorted(set(historique["id_site"]) - set(moyennes.index))
    if inconnus:
        logger.warning(
            "%s : sites inconnus du modèle, non prévus (réentraîner) : %s",
            production.version,
            inconnus,
        )
    historique = historique[historique["id_site"].isin(moyennes.index)]
    derniere_mesure = derniere_mesure_par_site(historique)
    en_retard = sorted(derniere_mesure[sites_en_retard(derniere_mesure, debut)].index)
    if en_retard:
        logger.warning(
            "%s : sites sans mesure à %s, non prévus : %s",
            production.version,
            debut - UNE_HEURE,
            en_retard,
        )
    return historique[~historique["id_site"].isin(en_retard)]


def fourchette(
    modele: RandomForestRegressor, X: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Centiles des prévisions des arbres, en ``conso_norm``. Les arbres ont appris
    sans les noms des colonnes : ils reçoivent un tableau, dans le même ordre."""
    arbres = np.stack([arbre.predict(X.to_numpy()) for arbre in modele.estimators_])
    return (
        np.percentile(arbres, CENTILE_BAS, axis=0),
        np.percentile(arbres, CENTILE_HAUT, axis=0),
    )


def prevoir(
    historique: pd.DataFrame,
    production: registre.ModeleProduction,
    debut: pd.Timestamp,
    horizon: int,
) -> pd.DataFrame:
    """Prévisions en kWh des ``horizon`` heures à partir de ``debut``, une ligne par
    site et par heure, aux colonnes de gold.prediction."""
    moyennes = production.moyennes
    historique = sites_prevus(historique, production, debut)
    if historique.empty:
        return pd.DataFrame(columns=COLONNES)
    lignes = ajouter_heures_a_prevoir(historique, debut, horizon)
    variables = construire_variables(lignes, moyennes, horizon)
    futur = variables[variables["heure"] >= debut].reset_index(drop=True)
    X = futur[noms_variables(horizon, moyennes)]
    # Le modèle prévoit conso_norm : on remultiplie par la moyenne du site
    moyenne = futur["id_site"].map(moyennes).to_numpy()
    prevue = np.clip(production.modele.predict(X), 0, None) * moyenne
    if isinstance(production.modele, RandomForestRegressor):
        bas, haut = fourchette(production.modele, X)
        # La moyenne des arbres peut sortir des centiles : la base exige
        # basse <= prévue <= haute
        basse = np.minimum(np.clip(bas, 0, None) * moyenne, prevue)
        haute = np.maximum(haut * moyenne, prevue)
    else:
        basse = haute = np.full(len(futur), np.nan)
    return pd.DataFrame(
        {
            "id_site": futur["id_site"],
            "heure_prevue": futur["heure"],
            # Arrondi de la colonne NUMERIC(12, 3), fait ici : il garde l'ordre
            # basse <= prévue <= haute
            "consommation_prevue_kwh": prevue.round(3),
            "consommation_basse_kwh": basse.round(3),
            "consommation_haute_kwh": haute.round(3),
            "version_modele": production.version,
        }
    )


def charger_production(horizon: int) -> registre.ModeleProduction | None:
    """Version ``production`` d'un horizon, ou None si aucune n'est enregistrée (avant
    le premier entraînement, par exemple)."""
    cache = os.environ.get("MODELE_CACHE_DIR")
    try:
        return registre.charger(horizon, Path(cache) if cache else None)
    except MlflowException as erreur:
        if erreur.error_code not in SANS_VERSION:
            raise
        logger.warning(
            "pas de version %s du modèle %s : horizon non prévu",
            registre.ALIAS,
            registre.nom_modele(horizon),
        )
        return None


def assembler(
    historique: pd.DataFrame,
    modeles: dict[int, registre.ModeleProduction | None],
    debut: pd.Timestamp,
) -> pd.DataFrame:
    """Une prévision par site et par heure : chaque horizon prévoit les heures que les
    horizons plus courts n'ont pas couvertes, site par site. Un site que la version
    24 h ne connaît pas (versions de dates différentes) garde ainsi ses 24 premières
    heures, prévues par le modèle 7 jours."""
    cles = ["id_site", "heure_prevue"]
    # Morceaux non vides seulement : concaténer un tableau vide ferait perdre aux
    # colonnes leur type (heures, nombres)
    morceaux: list[pd.DataFrame] = []
    for horizon in sorted(modeles):
        production = modeles[horizon]
        if production is None:
            continue
        previsions = prevoir(historique, production, debut, horizon)
        if morceaux:
            deja = pd.MultiIndex.from_frame(pd.concat(morceaux)[cles])
            previsions = previsions[
                ~pd.MultiIndex.from_frame(previsions[cles]).isin(deja)
            ]
        if not previsions.empty:
            morceaux.append(previsions)
    if not morceaux:
        return pd.DataFrame(columns=COLONNES)
    return pd.concat(morceaux, ignore_index=True)


def ecrire(conn: Connection, previsions: pd.DataFrame) -> None:
    """Ajoute les prévisions à gold.prediction (l'historique est gardé pour comparer
    prévu et réel). ``calculee_le`` vaut now() : la même heure pour toute la
    transaction, donc pour toute l'exécution."""
    # Bornes absentes (Ridge) : NULL, et non NaN
    lignes = previsions.astype(object).where(previsions.notna(), None)
    conn.execute(
        text(
            """
            INSERT INTO gold.prediction (
                id_site, heure_prevue, consommation_prevue_kwh,
                consommation_basse_kwh, consommation_haute_kwh, version_modele
            )
            VALUES (
                :id_site, :heure_prevue, :consommation_prevue_kwh,
                :consommation_basse_kwh, :consommation_haute_kwh, :version_modele
            )
            """
        ),
        lignes.to_dict("records"),
    )


def generer(maintenant: datetime | None = None) -> int:
    """Calcule et écrit les prévisions. Renvoie le nombre de lignes écrites."""
    debut = debut_des_previsions(maintenant or datetime.now(UTC))
    modeles = {horizon: charger_production(horizon) for horizon in HORIZONS}
    if not any(modeles.values()):
        logger.warning("aucun modèle en production : rien à prévoir")
        return 0
    with get_engine().begin() as conn:
        previsions = assembler(lire_historique(conn, debut), modeles, debut)
        if not previsions.empty:
            ecrire(conn, previsions)
    logger.info(
        "%d prévisions écrites, %d sites, à partir de %s (%s)",
        len(previsions),
        previsions["id_site"].nunique(),
        debut,
        ", ".join(m.version for m in modeles.values() if m),
    )
    return len(previsions)


if __name__ == "__main__":
    configure_logging("model")
    generer()
