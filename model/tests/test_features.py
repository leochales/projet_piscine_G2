import pandas as pd
from features import SITES, construire_variables, noms_variables

SANS_NORMALISATION = pd.Series({site: 1.0 for site in SITES})


def faux_site(site="SITE001", nb_heures=200):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2024-01-01", periods=nb_heures, freq="h", tz="UTC"
            ),
            "site_id": site,
            "conso": [float(i) for i in range(nb_heures)],
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
    debut_site2 = df[df["site_id"] == "SITE002"].head(24)
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
