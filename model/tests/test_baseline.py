from pathlib import Path

import pandas as pd
import pytest

from model.baseline import (
    ajouter_baselines,
    charger,
    chemin_par_defaut,
    scores,
    scores_reference,
)


def faux_jeu():
    """Deux sites sur 200 heures, triés comme le jeu du ticket 93 (heure, puis site).

    La consommation vaut le numéro de l'heure, plus 1000 pour SITE002 : on sait
    donc exactement ce que chaque baseline doit valoir.
    """
    heures = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    lignes = [
        {
            "id_site": site,
            "heure": heure,
            "moyenne_kw": float(i) + ajout,
            "taux_couverture": 1.0,
        }
        for site, ajout in [("SITE001", 0), ("SITE002", 1000)]
        for i, heure in enumerate(heures)
    ]
    return pd.DataFrame(lignes).sort_values(["heure", "id_site"], ignore_index=True)


def test_charger_trie_par_site_puis_par_heure(tmp_path):
    chemin = tmp_path / "dataset.parquet"
    faux_jeu().to_parquet(chemin, index=False)
    df = charger(chemin)
    debut = df.head(200)
    assert (debut["id_site"] == "SITE001").all()
    assert debut["heure"].is_monotonic_increasing


def test_baselines_prennent_la_valeur_passee_du_meme_site(tmp_path):
    chemin = tmp_path / "dataset.parquet"
    faux_jeu().to_parquet(chemin, index=False)
    df = ajouter_baselines(charger(chemin))
    site2 = df[df["id_site"] == "SITE002"].reset_index(drop=True)
    assert site2.loc[100, "baseline_veille"] == 1076
    assert site2.loc[180, "baseline_semaine"] == 1012
    # Les 24 premières heures de SITE002 n'ont pas de veille : pas de valeur de SITE001
    assert site2["baseline_veille"].head(24).isna().all()


def test_scores_sur_les_valeurs_mesurees_seulement():
    d = pd.DataFrame(
        {
            "consommation_kwh_brute": [100.0, 200.0, None, 300.0],
            "prevision": [110.0, 180.0, 999.0, None],
        }
    )
    resultat = scores(d, "prevision")
    # Seules les deux premières lignes comptent : erreurs de 10 et 20
    assert resultat["MAE"] == pytest.approx(15)
    assert resultat["RMSE"] == pytest.approx((250) ** 0.5)
    assert resultat["WAPE_%"] == pytest.approx(10)


def test_baseline_veille_suit_l_heure_meme_avec_un_trou():
    """En production, gold peut avoir des trous : 24 lignes ne font plus 24 heures."""
    df = faux_jeu()
    heures = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    trou = heures[76]
    df = df[~((df["id_site"] == "SITE001") & (df["heure"] == trou))]
    df = ajouter_baselines(df.sort_values(["id_site", "heure"], ignore_index=True))
    site1 = df[df["id_site"] == "SITE001"].set_index("heure")
    # La veille de l'heure 100 est l'heure manquante : pas de prévision
    assert pd.isna(site1.loc[heures[100], "baseline_veille"])
    # L'heure 101 prend bien l'heure 77, et non la 78 comme un décalage de 24 lignes
    assert site1.loc[heures[101], "baseline_veille"] == 77
    assert site1.loc[heures[180], "baseline_semaine"] == 12


def test_chemin_par_defaut_suit_dataset_output_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATASET_OUTPUT_DIR", str(tmp_path))
    assert chemin_par_defaut() == tmp_path / "dataset.parquet"
    monkeypatch.delenv("DATASET_OUTPUT_DIR")
    assert chemin_par_defaut() == Path("data/processed/dataset.parquet")


def test_scores_reference_sur_le_jeu_demande():
    df = faux_jeu()
    df["consommation_kwh_brute"] = df["moyenne_kw"]
    df["jeu"] = "entrainement"
    df.loc[df["heure"] >= df["heure"].min() + pd.Timedelta(hours=190), "jeu"] = "test"
    resultat = scores_reference(df, jeu="test")
    # Consommation qui monte d'1 kWh par heure : la veille se trompe de 24 partout,
    # y compris sur les premières heures du test (valeurs passées prises avant)
    assert set(resultat) == {"baseline_veille", "baseline_semaine"}
    assert resultat["baseline_veille"]["MAE"] == pytest.approx(24)
    assert resultat["baseline_semaine"]["MAE"] == pytest.approx(168)


def test_baselines_ignorent_les_heures_interpolees():
    """Comme le modèle : une heure sans mesure (interpolée dans le jeu du ticket 93)
    ne sert pas de valeur passée."""
    df = faux_jeu()
    heures = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    interpolee = (df["id_site"] == "SITE001") & (df["heure"] == heures[76])
    df.loc[interpolee, "taux_couverture"] = 0.0
    df = ajouter_baselines(df.sort_values(["id_site", "heure"], ignore_index=True))
    site1 = df[df["id_site"] == "SITE001"].set_index("heure")
    assert pd.isna(site1.loc[heures[100], "baseline_veille"])
    assert site1.loc[heures[101], "baseline_veille"] == 77
