import pandas as pd

from model.features import (
    SITES,
    construire_variables,
    moyennes_par_site,
    noms_variables,
)

SANS_NORMALISATION = pd.Series({site: 1.0 for site in SITES})


def faux_site(site="SITE001", nb_heures=200):
    return pd.DataFrame(
        {
            "heure": pd.date_range("2024-01-01", periods=nb_heures, freq="h", tz="UTC"),
            "id_site": site,
            "moyenne_kw": [float(i) for i in range(nb_heures)],
        }
    )


def test_lags_prennent_la_bonne_valeur_passee():
    df = construire_variables(faux_site(), SANS_NORMALISATION, 24)
    assert df.loc[100, "lag_24h"] == 76
    assert df.loc[180, "lag_7j"] == 12


def test_moyenne_glissante_sans_valeur_du_futur():
    df = construire_variables(faux_site(), SANS_NORMALISATION, 24)
    assert df.loc[100, "moyenne_24h"] == sum(range(53, 77)) / 24


def test_les_sites_ne_se_melangent_pas():
    deux_sites = pd.concat(
        [faux_site("SITE001"), faux_site("SITE002")], ignore_index=True
    )
    df = construire_variables(deux_sites, SANS_NORMALISATION, 24)
    debut_site2 = df[df["id_site"] == "SITE002"].head(24)
    assert debut_site2["lag_24h"].isna().all()


def test_calendrier():
    df = construire_variables(faux_site(), SANS_NORMALISATION, 24)
    assert df.loc[0, "jour_0"] == 1
    assert df.loc[0, "heure_0"] == 1
    assert df.loc[10, "heure_10"] == 1


def test_toutes_les_colonnes_meme_pour_un_seul_site():
    df = construire_variables(
        faux_site("SITE005", nb_heures=30), SANS_NORMALISATION, 24
    )
    assert all(nom in df.columns for nom in noms_variables(24))
    assert df.loc[0, "site_SITE005"] == 1
    assert df.loc[0, "site_SITE001"] == 0


def test_horizon_7_jours_sans_lag_trop_court():
    assert "lag_24h" not in noms_variables(168)
    assert "lag_7j" in noms_variables(168)


def test_moyenne_glissante_horizon_7_jours():
    df = construire_variables(faux_site(nb_heures=400), SANS_NORMALISATION, 168)
    assert df.loc[300, "moyenne_24h"] == sum(range(109, 133)) / 24


def test_heure_manquante_les_lags_suivent_le_temps():
    """En production, gold peut avoir des trous : 24 lignes ne font plus 24 heures."""
    site = faux_site()
    trou = site.loc[76, "heure"]
    avec_trou = site[site["heure"] != trou].reset_index(drop=True)
    df = construire_variables(avec_trou, SANS_NORMALISATION, 24).set_index("heure")
    heures = site["heure"]
    # La veille de l'heure 100 est l'heure manquante : pas de valeur
    assert pd.isna(df.loc[heures[100], "lag_24h"])
    # L'heure 101 prend bien l'heure 77, et non la 78 comme un décalage de 24 lignes
    assert df.loc[heures[101], "lag_24h"] == 77
    # Moyenne des heures 53 à 76 sans la 76 : 23 heures sur 24, assez pour la calculer
    assert df.loc[heures[100], "moyenne_24h"] == sum(range(53, 76)) / 23
    # Les heures ajoutées pour le calcul ne restent pas dans le résultat
    assert len(df) == len(avec_trou)


def test_normalisation_par_la_moyenne_du_site():
    deux_sites = pd.concat(
        [faux_site("SITE001", nb_heures=3), faux_site("SITE002", nb_heures=3)],
        ignore_index=True,
    )
    deux_sites.loc[deux_sites["id_site"] == "SITE002", "moyenne_kw"] *= 10
    moyennes = moyennes_par_site(deux_sites)
    df = construire_variables(deux_sites, moyennes, 24)
    # Même profil, à 10 fois l'échelle : mêmes valeurs normalisées
    site1 = df.loc[df["id_site"] == "SITE001", "conso_norm"].to_numpy()
    site2 = df.loc[df["id_site"] == "SITE002", "conso_norm"].to_numpy()
    assert list(site1) == list(site2) == [0.0, 1.0, 2.0]
