from datetime import datetime, timedelta

import pandas as pd
from donnees import boucher_trous_courts, decouper
from recuperer_historique import decouper_periode


def test_periodes_sans_chevauchement():
    heures = pd.date_range("2023-01-01", "2024-12-31 23:00", freq="h", tz="UTC")
    df = pd.DataFrame({"timestamp": heures})
    train, validation, test = decouper(df)
    assert train["timestamp"].max() < validation["timestamp"].min()
    assert validation["timestamp"].max() < test["timestamp"].min()
    assert len(train) + len(validation) + len(test) == len(df)


def test_trou_court_rempli():
    serie = pd.Series([100, None, 120])
    assert boucher_trous_courts(serie)[1] == 110


def test_trou_long_garde_vide():
    serie = pd.Series([100, None, None, None, 140])
    assert boucher_trous_courts(serie)[1:4].isna().all()


def test_decouper_periode_morceaux():
    debut = datetime(2023, 1, 1)
    fenetres = decouper_periode(debut, debut + timedelta(hours=2500), 1000)
    assert [nb for _, _, nb in fenetres] == [1000, 1000, 500]
