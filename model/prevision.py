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
Ridge n'en donne pas (bornes NULL).

Pic de l'heure (SMARTOPS-104) : le jeu d'entraînement n'a qu'une mesure par heure, donc
pas de pic des minutes, et aucun modèle ne l'apprend. ``pic_prevu_kw`` est la
consommation prévue (kWh d'une heure = kW moyens) multipliée par le rapport pic/moyenne
du site, médiane sur ``HISTORIQUE_UTILE``. Le pic d'une heure passée est son « pic
soutenu » : la plus forte valeur tenue 3 minutes mesurées consécutives (silver), selon
la règle de la détection des pics de l'ETL (``db/17_gold_alertes.sql``). Le pic d'une
seule minute dépasserait le seuil bien plus souvent que les alertes réelles. Seules les
heures terminées et mesurées sur au moins ``COUVERTURE_MIN_MOYENNE`` de leurs minutes
comptent : une heure en panne ou imputée a un pic proche de sa moyenne.

Le rapport est pris par heure de la journée quand elle a assez d'heures mesurées, sinon
pour tout le site. Sa fourchette applique le même rapport aux bornes de consommation.
Un site sans assez d'heures mesurées n'a pas de pic prévu (NULL), avec un
avertissement. ``pic_prevu`` est vrai quand le pic prévu atteint le seuil d'alerte du
site (``app.site.seuil_alerte_pct`` de ``capacite_kw``), le même que l'ETL.

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
from model import alerte_pic, registre
from model.features import (
    COUVERTURE_MIN_MOYENNE,
    HEURES,
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
# Colonnes des prévisions du modèle (calculee_le : valeur par défaut de gold.prediction)
COLONNES = [
    "id_site",
    "heure_prevue",
    "consommation_prevue_kwh",
    "consommation_basse_kwh",
    "consommation_haute_kwh",
    "version_modele",
]
# Colonnes du pic de l'heure, ajoutées par ajouter_pics
COLONNES_PIC = ["pic_prevu_kw", "pic_bas_kw", "pic_haut_kw", "pic_prevu"]
# Heures mesurées nécessaires au rapport pic/moyenne d'un site, et à celui d'une heure
# de la journée (en dessous, l'heure prend le rapport du site)
HEURES_MIN_RATIO_SITE = 24
HEURES_MIN_RATIO_HEURE = 3
# Pic soutenu (lire_pics) : écart maximal entre deux minutes mesurées d'une même série.
# Même règle que la détection des pics de l'ETL (db/17_gold_alertes.sql), qui coupe la
# série quand l'écart dépasse 5 minutes : 10:00, 10:06, 10:12 ne sont pas une série
ECART_MAX_PIC_SOUTENU = pd.Timedelta(minutes=5)


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
    comprise (l'ETL la met à jour chaque minute).

    Un site actif sans aucune ligne sur cette période (panne de plus de 28 jours,
    site jamais collecté) revient quand même, sur une ligne vide : ``sites_prevus``
    l'écarte alors avec un avertissement, comme un site en retard, au lieu qu'il
    disparaisse sans rien dire."""
    lignes = conn.execute(
        text(
            """
            SELECT s.id_site, c.heure, c.moyenne_kw, c.taux_couverture
            FROM app.site AS s
            LEFT JOIN gold.consommation_horaire AS c
                ON c.id_site = s.id_site
                AND c.heure >= :depuis AND c.heure < :debut
            WHERE s.statut = 'active'
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


def lire_pics(conn: Connection, debut: pd.Timestamp) -> pd.DataFrame:
    """Pic soutenu et moyenne des heures terminées et bien mesurées des sites actifs,
    sur ``HISTORIQUE_UTILE`` : de quoi calculer le rapport pic/moyenne de chaque site
    (``ratios_pic``).

    ``pic_kw`` est le pic soutenu de l'heure : la plus forte valeur tenue par 3 minutes
    mesurées consécutives (``consumption_kw_raw``, jamais une valeur imputée), comme
    les pics qui ouvrent une alerte dans l'ETL : deux minutes successives sont à
    ``ECART_MAX_PIC_SOUTENU`` au plus. Les 3 minutes sont dans la même heure : un
    triplet à cheval sur deux heures (10:58, 10:59, 11:00) n'est compté dans aucune,
    pour que le pic et la moyenne de l'heure portent sur les mêmes minutes. Une heure
    compte si au moins ``COUVERTURE_MIN_MOYENNE`` de ses minutes ont une consommation
    mesurée (imputées exclues)."""
    lignes = conn.execute(
        text(
            """
            WITH minutes AS (
                SELECT
                    r.id_site,
                    r.horodatage,
                    lag(r.horodatage, 1) OVER w AS horodatage_1,
                    lag(r.horodatage, 2) OVER w AS horodatage_2,
                    least(
                        r.consumption_kw_raw,
                        lag(r.consumption_kw_raw, 1) OVER w,
                        lag(r.consumption_kw_raw, 2) OVER w
                    ) AS soutenu_kw
                FROM silver.silver_readings AS r
                JOIN app.site AS s ON s.id_site = r.id_site
                WHERE s.statut = 'active'
                  AND r.consumption_kw_raw IS NOT NULL
                  AND r.horodatage >= :depuis AND r.horodatage < :debut
                WINDOW w AS (PARTITION BY r.id_site ORDER BY r.horodatage)
            ),
            soutenus AS (
                SELECT
                    id_site,
                    date_trunc('hour', horodatage, 'UTC') AS heure,
                    max(soutenu_kw) AS pic_kw
                FROM minutes
                WHERE horodatage - horodatage_1 <= :ecart_max
                  AND horodatage_1 - horodatage_2 <= :ecart_max
                  AND date_trunc('hour', horodatage_2, 'UTC')
                  = date_trunc('hour', horodatage, 'UTC')
                GROUP BY id_site, date_trunc('hour', horodatage, 'UTC')
            )
            SELECT c.id_site, c.heure, p.pic_kw, c.moyenne_kw
            FROM gold.consommation_horaire AS c
            JOIN soutenus AS p ON p.id_site = c.id_site AND p.heure = c.heure
            WHERE c.heure_complete
              AND c.moyenne_kw > 0
              AND c.nb_mesures - c.nb_imputees >= :minutes_min
              AND c.heure >= :depuis AND c.heure < :debut
            """
        ),
        {
            "depuis": debut - HISTORIQUE_UTILE,
            "debut": debut,
            "ecart_max": ECART_MAX_PIC_SOUTENU.to_pytimedelta(),
            "minutes_min": int(np.ceil(60 * COUVERTURE_MIN_MOYENNE)),
        },
    ).all()
    df = pd.DataFrame(lignes, columns=["id_site", "heure", "pic_kw", "moyenne_kw"])
    return df.assign(
        heure=pd.to_datetime(df["heure"], utc=True),
        pic_kw=df["pic_kw"].astype(float),
        moyenne_kw=df["moyenne_kw"].astype(float),
    )


def lire_sites(conn: Connection) -> pd.DataFrame:
    """Seuil d'alerte (``seuil_kw``) et capacité (``capacite_kw``) de chaque site actif,
    en kW, indexés par ``id_site``. Le seuil vaut ``seuil_alerte_pct`` % de la capacité,
    arrondi comme dans la détection des pics mesurés de l'ETL."""
    lignes = conn.execute(
        text(
            """
            SELECT
                id_site,
                round(capacite_kw * seuil_alerte_pct / 100, 2) AS seuil_kw,
                capacite_kw
            FROM app.site
            WHERE statut = 'active'
            """
        )
    ).all()
    sites = pd.DataFrame(lignes, columns=["id_site", "seuil_kw", "capacite_kw"])
    return sites.set_index("id_site").astype(float)


def ratios_pic(pics: pd.DataFrame) -> pd.Series:
    """Rapport pic/moyenne de chaque site et de chaque heure de la journée (index
    ``id_site``, ``heure_jour``). Médiane des heures mesurées : celle de l'heure de la
    journée si elle en a ``HEURES_MIN_RATIO_HEURE``, sinon celle du site. Un site qui
    n'a pas ``HEURES_MIN_RATIO_SITE`` heures mesurées est absent.

    L'heure de la journée est celle de l'horodatage, comme dans les variables du
    modèle. Le rapport vaut au moins 1 : le pic d'une heure ne descend pas sous sa
    moyenne."""
    pics = pics.assign(
        ratio=pics["pic_kw"] / pics["moyenne_kw"], heure_jour=pics["heure"].dt.hour
    )
    par_site = pics.groupby("id_site")["ratio"].agg(["median", "count"])
    par_site = par_site.loc[par_site["count"] >= HEURES_MIN_RATIO_SITE, "median"]
    par_heure = pics.groupby(["id_site", "heure_jour"])["ratio"].agg(
        ["median", "count"]
    )
    par_heure = par_heure.loc[par_heure["count"] >= HEURES_MIN_RATIO_HEURE, "median"]
    ratios = (
        par_heure.unstack("heure_jour")
        .reindex(index=par_site.index, columns=HEURES)
        .where(lambda r: r.notna(), par_site, axis=0)
        .clip(lower=1.0)
    )
    ratios.index.name = "id_site"
    ratios.columns.name = "heure_jour"
    return ratios.stack()


def ajouter_pics(
    previsions: pd.DataFrame, ratios: pd.Series, seuils: pd.Series
) -> pd.DataFrame:
    """Ajoute le pic prévu de chaque heure (``COLONNES_PIC``) : consommation prévue et
    bornes multipliées par le rapport pic/moyenne du site à cette heure de la journée.
    Le rapport est le même pour les trois valeurs : l'ordre basse <= prévue <= haute
    exigé par la base est gardé. Sans rapport pour le site, le pic est NULL et
    ``pic_prevu`` faux."""
    sans_ratio = sorted(
        set(previsions["id_site"]) - set(ratios.index.get_level_values("id_site"))
    )
    if sans_ratio:
        logger.warning(
            "sites avec moins de %d heures mesurées : pic de l'heure non prévu : %s",
            HEURES_MIN_RATIO_SITE,
            sans_ratio,
        )
    cles = pd.MultiIndex.from_arrays(
        [previsions["id_site"], previsions["heure_prevue"].dt.hour],
        names=["id_site", "heure_jour"],
    )
    ratio = ratios.reindex(cles).to_numpy(dtype=float)

    def pic(colonne: str) -> np.ndarray:
        # Arrondi de la colonne NUMERIC(10, 2), qui garde l'ordre des trois valeurs
        return (previsions[colonne].to_numpy(dtype=float) * ratio).round(2)

    pic_prevu_kw = pic("consommation_prevue_kwh")
    seuil = previsions["id_site"].map(seuils).to_numpy(dtype=float)
    return previsions.assign(
        pic_prevu_kw=pic_prevu_kw,
        pic_bas_kw=pic("consommation_basse_kwh"),
        pic_haut_kw=pic("consommation_haute_kwh"),
        # Pic ou seuil inconnu (NaN) : la comparaison est fausse
        pic_prevu=pic_prevu_kw >= seuil,
    )


def ecrire(conn: Connection, previsions: pd.DataFrame) -> None:
    """Ajoute les prévisions à gold.prediction (l'historique est gardé pour comparer
    prévu et réel). ``calculee_le`` vaut now() : la même heure pour toute la
    transaction, donc pour toute l'exécution."""
    # Pic non calculé : NULL, et pic_prevu faux (colonne NOT NULL)
    previsions = previsions.reindex(columns=COLONNES + COLONNES_PIC)
    previsions["pic_prevu"] = previsions["pic_prevu"].fillna(False).astype(bool)
    # Bornes ou pic absents (Ridge, site sans historique) : NULL, et non NaN
    lignes = previsions.astype(object).where(previsions.notna(), None)
    conn.execute(
        text(
            """
            INSERT INTO gold.prediction (
                id_site, heure_prevue, consommation_prevue_kwh,
                consommation_basse_kwh, consommation_haute_kwh, version_modele,
                pic_prevu_kw, pic_bas_kw, pic_haut_kw, pic_prevu
            )
            VALUES (
                :id_site, :heure_prevue, :consommation_prevue_kwh,
                :consommation_basse_kwh, :consommation_haute_kwh, :version_modele,
                :pic_prevu_kw, :pic_bas_kw, :pic_haut_kw, :pic_prevu
            )
            """
        ),
        lignes.to_dict("records"),
    )


def generer(maintenant: datetime | None = None) -> int:
    """Calcule et écrit les prévisions, puis les alertes de pic prévu qui en découlent
    (``model.alerte_pic``), dans la même transaction : si un calcul ou une écriture
    échoue, aucune alerte n'est ouverte ni fermée. Sans prévision (aucun modèle en
    production, aucun site prévu), seules les alertes dont le pic est passé sont
    terminées. Renvoie le nombre de prévisions écrites."""
    debut = debut_des_previsions(maintenant or datetime.now(UTC))
    modeles = {horizon: charger_production(horizon) for horizon in HORIZONS}
    if not any(modeles.values()):
        logger.warning("aucun modèle en production : rien à prévoir")
        with get_engine().begin() as conn:
            alerte_pic.terminer(conn, [])
        return 0
    with get_engine().begin() as conn:
        previsions = assembler(lire_historique(conn, debut), modeles, debut)
        if previsions.empty:
            alerte_pic.terminer(conn, [])
        else:
            sites = lire_sites(conn)
            previsions = ajouter_pics(
                previsions, ratios_pic(lire_pics(conn, debut)), sites["seuil_kw"]
            )
            ecrire(conn, previsions)
            alerte_pic.mettre_a_jour(conn, previsions, sites)
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
