import os
from datetime import datetime, timedelta

import pandas as pd
import requests

API_MOCK_URL = os.getenv("MOCK_API_URL", "http://10.43.43.80:8000")
SITES = ["SITE001", "SITE002", "SITE003", "SITE004", "SITE005", "SITE006", "SITE007"]
DEBUT = datetime(2023, 1, 1)
FIN = datetime(2025, 1, 1)
HEURES_PAR_APPEL = 1000


def decouper_periode(debut, fin, taille):
    fenetres = []
    while debut < fin:
        nb_heures = min(taille, int((fin - debut) / timedelta(hours=1)))
        fenetres.append((debut, debut + timedelta(hours=nb_heures), nb_heures))
        debut += timedelta(hours=nb_heures)
    return fenetres


def recuperer_site(site_id):
    lignes = []
    for debut, fin, nb_heures in decouper_periode(DEBUT, FIN, HEURES_PAR_APPEL):
        params = {
            "site_id": site_id,
            "start_time": debut.isoformat(),
            "end_time": fin.isoformat(),
            "limit": nb_heures,
        }
        reponse = requests.get(
            f"{API_MOCK_URL}/api/v1/readings", params=params, timeout=30
        )
        reponse.raise_for_status()
        lignes.extend(reponse.json())
    return lignes


if __name__ == "__main__":
    toutes_les_lignes = []
    for site_id in SITES:
        print(f"Récupération de {site_id}...")
        toutes_les_lignes.extend(recuperer_site(site_id))

    df = pd.DataFrame(toutes_les_lignes)
    os.makedirs("data/raw", exist_ok=True)
    df.to_csv("data/raw/readings.csv", index=False)
    print(df.shape)
    print(df.head())
