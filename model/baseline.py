import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from model.donnees import charger, decouper, nettoyer

df = nettoyer(charger("model/data/raw/readings.csv"))


par_site = df.groupby("site_id")["conso"]
df["baseline_veille"] = par_site.shift(24)
df["baseline_semaine"] = par_site.shift(168)


print(df.shape)
print(df.columns.tolist())
print(df.head())
print(df.groupby("site_id")["consumption_kwh"].agg(["count", "mean", "min", "max"]))
print(df.isna().mean() * 100)
print("Vides avant :", df["consumption_kwh"].isna().sum())
print("Vides après :", df["conso"].isna().sum())


def scores(d, colonne):
    d = d.dropna(subset=["consumption_kwh", colonne])
    mae = mean_absolute_error(d["consumption_kwh"], d[colonne])
    rmse = np.sqrt(mean_squared_error(d["consumption_kwh"], d[colonne]))
    return pd.Series(
        {"MAE": mae, "RMSE": rmse, "MAE_%": 100 * mae / d["consumption_kwh"].mean()}
    )


_, _, test = decouper(df)

for colonne in ["baseline_veille", "baseline_semaine"]:
    print("=====", colonne)
    print(scores(test, colonne).round(2))
    print(test.groupby("site_id").apply(scores, colonne).round(2))
