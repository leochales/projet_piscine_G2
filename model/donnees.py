import pandas as pd

# def charger(dossier):
#     fichiers = glob.glob(f"{dossier}/*.csv")
#     df = pd.concat([pd.read_csv(f) for f in fichiers], ignore_index=True)
#     df["timestamp"] = pd.to_datetime(df["timestamp"])
#     return df.sort_values(["site_id", "timestamp"]).reset_index(drop=True)


def charger(chemin):
    df = pd.read_csv(chemin)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values(["site_id", "timestamp"]).reset_index(drop=True)


def boucher_trous_courts(serie, max_heures=2):
    est_vide = serie.isna()
    numero_bloc = (est_vide != est_vide.shift()).cumsum()
    taille_bloc = est_vide.groupby(numero_bloc).transform("sum")
    serie_interpolee = serie.interpolate(limit_area="inside")
    a_remplir = est_vide & (taille_bloc <= max_heures)
    return serie.where(~a_remplir, serie_interpolee)


def nettoyer(df):
    df = df.copy()
    df["conso"] = df.groupby("site_id")["consumption_kwh"].transform(
        boucher_trous_courts
    )
    return df


DEBUT_VALIDATION = pd.Timestamp("2024-07-01", tz="UTC")
DEBUT_TEST = pd.Timestamp("2024-10-01", tz="UTC")


def decouper(df):
    train = df[df["timestamp"] < DEBUT_VALIDATION]
    validation = df[
        (df["timestamp"] >= DEBUT_VALIDATION) & (df["timestamp"] < DEBUT_TEST)
    ]
    test = df[df["timestamp"] >= DEBUT_TEST]
    return train, validation, test
