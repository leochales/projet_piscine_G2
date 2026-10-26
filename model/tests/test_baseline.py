import pandas as pd
import pytest

from model.baseline import ajouter_baselines, charger, scores


def faux_jeu():
    """Deux sites sur 200 heures, triés comme le jeu du ticket 93 (heure, puis site).

    La consommation vaut le numéro de l'heure, plus 1000 pour SITE002 : on sait
    donc exactement ce que chaque baseline doit valoir.
    """
    heures = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    lignes = [
        {"id_site": site, "heure": heure, "moyenne_kw": float(i) + ajout}
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
