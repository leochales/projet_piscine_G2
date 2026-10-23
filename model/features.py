import pandas as pd


def moyennes_par_site(train, colonne="conso"):
    return train.groupby("site_id")[colonne].mean()


def normaliser(df, moyennes, colonne="conso"):
    df = df.copy()
    df["conso_norm"] = df[colonne] / df["site_id"].map(moyennes)
    return df


LAGS = {"lag_24h": 24, "lag_7j": 168, "lag_14j": 336, "lag_28j": 672}
MOYENNES = {"moyenne_24h": 24, "moyenne_7j": 168}
HEURES = list(range(24))
JOURS = list(range(7))
SITES = ["SITE001", "SITE002", "SITE003", "SITE004", "SITE005", "SITE006", "SITE007"]


def lags_utilisables(horizon):
    return {nom: decalage for nom, decalage in LAGS.items() if decalage >= horizon}


def moyenne_glissante(serie, decalage, fenetre):
    return serie.shift(decalage).rolling(fenetre, min_periods=int(fenetre * 0.8)).mean()


def ajouter_lags(df, horizon):
    df = df.copy()
    par_site = df.groupby("site_id")["conso_norm"]
    for nom, decalage in lags_utilisables(horizon).items():
        df[nom] = par_site.shift(decalage)
    for nom, fenetre in MOYENNES.items():
        df[nom] = par_site.transform(moyenne_glissante, horizon, fenetre)
    return df


def noms_variables(horizon):
    return (
        list(lags_utilisables(horizon))
        + list(MOYENNES)
        + [f"heure_{h}" for h in HEURES]
        + [f"jour_{j}" for j in JOURS]
        + [f"site_{s}" for s in SITES]
    )


def construire_variables(df, moyennes, horizon):
    df = normaliser(df, moyennes)
    df = ajouter_lags(df, horizon)
    return ajouter_calendrier(df)


def encoder(serie, valeurs, prefixe):
    categories = pd.Series(pd.Categorical(serie, categories=valeurs), index=serie.index)
    return pd.get_dummies(categories, prefix=prefixe, dtype=int)


def ajouter_calendrier(df):
    df = df.copy()
    heures = encoder(df["timestamp"].dt.hour, HEURES, "heure")
    jours = encoder(df["timestamp"].dt.dayofweek, JOURS, "jour")
    sites = encoder(df["site_id"], SITES, "site")
    return pd.concat([df, heures, jours, sites], axis=1)
