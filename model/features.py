"""Variables du modèle de prévision (SMARTOPS-29), communes à l'entraînement et à la
prévision.

Entrée : une ligne par site et par heure, au format de ``gold.consommation_horaire``
(le jeu du ticket 93 en a les colonnes). La consommation de l'heure est
``moyenne_kw`` : elle reste juste quand des minutes manquent, contrairement à
``consommation_kwh``.

Variables, pour un horizon donné (24 h ou 7 jours) :
  - consommation divisée par la moyenne du site sur l'entraînement (``conso_norm``),
    pour qu'un modèle unique serve aux 7 sites ;
  - valeurs passées (lags) et moyennes glissantes, prises au moins ``horizon`` heures
    avant : au moment de prévoir, les heures plus récentes ne sont pas encore connues ;
  - heure du jour, jour de la semaine et site, en colonnes 0/1.

Les décalages se font dans le temps, pas en lignes : gold peut avoir des heures
absentes, qui sont ajoutées vides avant de décaler. ``valeurs_passees`` sert aussi à la
prévision de référence (``model.baseline``) : le modèle et la référence ont la même
définition de « la veille ».

Pour prévoir, ajouter d'abord les heures à prévoir avec ``ajouter_heures_a_prevoir`` :
leurs variables sont calculées à partir de l'historique, leur consommation reste vide.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

COLONNE_CONSO = "moyenne_kw"

LAGS = {"lag_24h": 24, "lag_7j": 168, "lag_14j": 336, "lag_28j": 672}
MOYENNES = {"moyenne_24h": 24, "moyenne_7j": 168}
# Part minimale d'heures connues dans une moyenne glissante
COUVERTURE_MIN_MOYENNE = 0.8
HEURES = list(range(24))
JOURS = list(range(7))
SITES = ["SITE001", "SITE002", "SITE003", "SITE004", "SITE005", "SITE006", "SITE007"]


def moyennes_par_site(train: pd.DataFrame, colonne: str = COLONNE_CONSO) -> pd.Series:
    """Consommation moyenne de chaque site, calculée sur l'entraînement seulement."""
    return train.groupby("id_site")[colonne].mean()


def verifier_entree(df: pd.DataFrame, moyennes: pd.Series) -> None:
    """Arrête avec un message clair plutôt que de produire des variables vides ou
    infinies sans prévenir."""
    if df.empty:
        raise ValueError("Aucune ligne de consommation : pas de variables à construire")
    sites = df["id_site"].unique()
    inconnus = sorted(set(sites) - set(SITES))
    if inconnus:
        raise ValueError(f"Sites inconnus du modèle : {inconnus}")
    sans_moyenne = sorted(s for s in sites if not moyennes.get(s, 0) > 0)
    if sans_moyenne:
        raise ValueError(
            f"Moyenne d'entraînement absente ou nulle pour {sans_moyenne} : "
            "impossible de normaliser la consommation"
        )


def normaliser(
    df: pd.DataFrame, moyennes: pd.Series, colonne: str = COLONNE_CONSO
) -> pd.DataFrame:
    df = df.copy()
    df["conso_norm"] = df[colonne] / df["id_site"].map(moyennes)
    return df


def lags_utilisables(horizon: int) -> dict[str, int]:
    """Lags connus au moment de prévoir : au moins ``horizon`` heures avant."""
    return {nom: decalage for nom, decalage in LAGS.items() if decalage >= horizon}


def completer_heures(df: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par site et par heure, de la première à la dernière heure du site,
    triée par site puis par heure.

    Les heures absentes sont ajoutées, avec des valeurs vides : sur cette grille, un
    décalage de 24 lignes fait toujours 24 heures."""
    if df.empty:
        return df.copy()
    morceaux = []
    for site, groupe in df.groupby("id_site", sort=False):
        heures = pd.date_range(
            groupe["heure"].min(), groupe["heure"].max(), freq="h", name="heure"
        )
        complet = groupe.drop(columns="id_site").set_index("heure").reindex(heures)
        complet.insert(0, "id_site", site)
        morceaux.append(complet.reset_index())
    return pd.concat(morceaux, ignore_index=True)


def moyenne_glissante(serie: pd.Series, decalage: int, fenetre: int) -> pd.Series:
    """Moyenne des ``fenetre`` heures qui finissent ``decalage`` heures avant
    (``serie`` : un site, une ligne par heure)."""
    min_heures = int(fenetre * COUVERTURE_MIN_MOYENNE)
    return serie.shift(decalage).rolling(fenetre, min_periods=min_heures).mean()


def calculer_sur_grille(
    df: pd.DataFrame,
    colonne: str,
    calculs: dict[str, Callable[[pd.Series], pd.Series]],
) -> pd.DataFrame:
    """Applique chaque calcul à la série horaire complète de chaque site et renvoie
    les résultats sur les lignes de ``df`` (même index), une colonne par calcul."""
    grille = completer_heures(df[["id_site", "heure", colonne]])
    par_site = grille.groupby("id_site")[colonne]
    for nom, calcul in calculs.items():
        grille[nom] = par_site.transform(calcul)
    resultat = df[["id_site", "heure"]].merge(
        grille[["id_site", "heure", *calculs]],
        on=["id_site", "heure"],
        how="left",
        validate="one_to_one",
    )
    # merge renumérote les lignes : on garde l'index de df
    resultat.index = df.index
    return resultat[list(calculs)]


def decaler(decalage: int) -> Callable[[pd.Series], pd.Series]:
    return lambda serie: serie.shift(decalage)


def valeurs_passees(
    df: pd.DataFrame, colonne: str, decalages: dict[str, int]
) -> pd.DataFrame:
    """Valeur de ``colonne`` du même site, N heures plus tôt (vide si cette heure
    manque), une colonne par décalage."""
    calculs = {nom: decaler(d) for nom, d in decalages.items()}
    return calculer_sur_grille(df, colonne, calculs)


def moyenne_decalee(decalage: int, fenetre: int) -> Callable[[pd.Series], pd.Series]:
    return lambda serie: moyenne_glissante(serie, decalage, fenetre)


def ajouter_lags(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Ajoute les lags et les moyennes glissantes, calculés dans le temps."""
    calculs = {nom: decaler(d) for nom, d in lags_utilisables(horizon).items()}
    for nom, fenetre in MOYENNES.items():
        calculs[nom] = moyenne_decalee(horizon, fenetre)
    return pd.concat([df, calculer_sur_grille(df, "conso_norm", calculs)], axis=1)


def ajouter_heures_a_prevoir(
    historique: pd.DataFrame, debut: pd.Timestamp, nb_heures: int
) -> pd.DataFrame:
    """Ajoute, pour chaque site de l'historique, les ``nb_heures`` heures à partir de
    ``debut``, sans consommation. ``construire_variables`` calcule ensuite leurs
    variables à partir de l'historique, et le modèle prédit ces lignes."""
    heures = pd.date_range(debut, periods=nb_heures, freq="h")
    a_prevoir = pd.MultiIndex.from_product(
        [historique["id_site"].unique(), heures], names=["id_site", "heure"]
    ).to_frame(index=False)
    connues = historique.set_index(["id_site", "heure"]).index
    a_prevoir = a_prevoir[
        ~a_prevoir.set_index(["id_site", "heure"]).index.isin(connues)
    ]
    return pd.concat([historique, a_prevoir], ignore_index=True)


def encoder(serie: pd.Series, valeurs: list, prefixe: str) -> pd.DataFrame:
    """Une colonne 0/1 par valeur possible, même absente des données."""
    categories = pd.Series(pd.Categorical(serie, categories=valeurs), index=serie.index)
    return pd.get_dummies(categories, prefix=prefixe, dtype=int)


def ajouter_calendrier(df: pd.DataFrame) -> pd.DataFrame:
    """Heure du jour et jour de la semaine lus sur ``heure`` telle quelle, sans
    conversion en heure de Paris : les horodatages de l'API Mock et du CSV sont l'heure
    du simulateur, sans changement d'heure, enregistrée comme de l'UTC (ticket 93).
    Les bureaux y commencent à 8 h toute l'année. Convertir en heure de Paris décalerait
    ce profil d'une heure l'été."""
    heures = encoder(df["heure"].dt.hour, HEURES, "heure")
    jours = encoder(df["heure"].dt.dayofweek, JOURS, "jour")
    sites = encoder(df["id_site"], SITES, "site")
    return pd.concat([df, heures, jours, sites], axis=1)


def noms_variables(horizon: int) -> list[str]:
    """Colonnes données au modèle, dans l'ordre."""
    return (
        list(lags_utilisables(horizon))
        + list(MOYENNES)
        + [f"heure_{h}" for h in HEURES]
        + [f"jour_{j}" for j in JOURS]
        + [f"site_{s}" for s in SITES]
    )


def construire_variables(
    df: pd.DataFrame, moyennes: pd.Series, horizon: int
) -> pd.DataFrame:
    verifier_entree(df, moyennes)
    df = normaliser(df, moyennes)
    df = ajouter_lags(df, horizon)
    return ajouter_calendrier(df)
