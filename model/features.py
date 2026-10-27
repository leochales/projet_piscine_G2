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
absentes, qui sont ajoutées vides avant de décaler.
"""

from __future__ import annotations

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
    """Une ligne par site et par heure, de la première à la dernière heure du site.

    Les heures absentes sont ajoutées, avec des valeurs vides : sur cette grille, un
    décalage de 24 lignes fait toujours 24 heures."""
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


def ajouter_lags(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Ajoute les lags et les moyennes glissantes, calculés sur la grille complète."""
    lags = lags_utilisables(horizon)
    grille = completer_heures(df[["id_site", "heure", "conso_norm"]])
    grille = grille.sort_values(["id_site", "heure"], ignore_index=True)
    par_site = grille.groupby("id_site")["conso_norm"]
    for nom, decalage in lags.items():
        grille[nom] = par_site.shift(decalage)
    for nom, fenetre in MOYENNES.items():
        grille[nom] = par_site.transform(moyenne_glissante, horizon, fenetre)

    colonnes = [*lags, *MOYENNES]
    resultat = df.merge(
        grille[["id_site", "heure", *colonnes]],
        on=["id_site", "heure"],
        how="left",
        validate="one_to_one",
    )
    # merge renumérote les lignes : on garde l'index de df
    resultat.index = df.index
    return resultat


def encoder(serie: pd.Series, valeurs: list, prefixe: str) -> pd.DataFrame:
    """Une colonne 0/1 par valeur possible, même absente des données."""
    categories = pd.Series(pd.Categorical(serie, categories=valeurs), index=serie.index)
    return pd.get_dummies(categories, prefix=prefixe, dtype=int)


def ajouter_calendrier(df: pd.DataFrame) -> pd.DataFrame:
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
    df = normaliser(df, moyennes)
    df = ajouter_lags(df, horizon)
    return ajouter_calendrier(df)
