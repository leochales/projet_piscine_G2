import pandas as pd
import pytest

from model.features import (
    ajouter_heures_a_prevoir,
    construire_variables,
    moyennes_par_site,
    noms_variables,
)

SITES = ["SITE001", "SITE002", "SITE003", "SITE004", "SITE005", "SITE006", "SITE007"]
# Moyenne de 1 pour chaque site : conso_norm vaut la consommation
SANS_NORMALISATION = pd.Series({site: 1.0 for site in SITES})


def faux_site(site="SITE001", nb_heures=200):
    return pd.DataFrame(
        {
            "heure": pd.date_range("2024-01-01", periods=nb_heures, freq="h", tz="UTC"),
            "id_site": site,
            "moyenne_kw": [float(i) for i in range(nb_heures)],
            "taux_couverture": 1.0,
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
    assert all(nom in df.columns for nom in noms_variables(24, SANS_NORMALISATION))
    assert df.loc[0, "site_SITE005"] == 1
    assert df.loc[0, "site_SITE001"] == 0


def test_horizon_7_jours_sans_lag_trop_court():
    assert "lag_24h" not in noms_variables(168, SANS_NORMALISATION)
    assert "lag_7j" in noms_variables(168, SANS_NORMALISATION)


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


def test_site_inconnu_refuse():
    with pytest.raises(ValueError, match="SITE999.*réentraîner"):
        construire_variables(faux_site("SITE999"), SANS_NORMALISATION, 24)


def test_site_sans_moyenne_d_entrainement_refuse():
    moyennes = pd.Series({"SITE001": 1.0})
    with pytest.raises(ValueError, match="SITE002"):
        construire_variables(faux_site("SITE002"), moyennes, 24)


def test_moyenne_nulle_refusee():
    moyennes = pd.Series({"SITE001": 0.0})
    with pytest.raises(ValueError, match="SITE001"):
        construire_variables(faux_site(), moyennes, 24)


def test_entree_vide_refusee_avec_un_message_clair():
    with pytest.raises(ValueError, match="Aucune ligne"):
        construire_variables(faux_site().iloc[0:0], SANS_NORMALISATION, 24)


def test_heures_a_prevoir_avec_les_variables_de_l_historique():
    historique = faux_site(nb_heures=100)
    debut = historique["heure"].max() + pd.Timedelta(hours=1)
    df = ajouter_heures_a_prevoir(historique, debut, 24)
    assert len(df) == 124
    df = construire_variables(df, SANS_NORMALISATION, 24)
    futur = df[df["heure"] >= debut].reset_index(drop=True)
    # Pas de consommation à prévoir, mais des lags pris dans l'historique
    assert futur["moyenne_kw"].isna().all()
    assert futur.loc[0, "lag_24h"] == 76
    assert futur.loc[23, "lag_24h"] == 99


def test_heures_a_prevoir_deja_connues_pas_en_double():
    historique = faux_site(nb_heures=100)
    debut = historique["heure"].max() - pd.Timedelta(hours=1)
    df = ajouter_heures_a_prevoir(historique, debut, 24)
    # Les 2 premières heures existent déjà : seules les 22 suivantes sont ajoutées
    assert len(df) == 122


@pytest.mark.parametrize("horizon", [0, 12, 48])
def test_horizon_non_prevu_refuse(horizon):
    # À 0, les moyennes glissantes contiendraient la consommation à prévoir
    with pytest.raises(ValueError, match="Horizon"):
        construire_variables(faux_site(), SANS_NORMALISATION, horizon)


def test_heure_en_double_refusee():
    site = faux_site()
    with pytest.raises(ValueError, match="double"):
        construire_variables(pd.concat([site, site.head(1)]), SANS_NORMALISATION, 24)


def test_colonne_manquante_refusee():
    with pytest.raises(ValueError, match="taux_couverture"):
        construire_variables(
            faux_site().drop(columns="taux_couverture"), SANS_NORMALISATION, 24
        )


def test_heure_interpolee_traitee_comme_absente():
    """Une heure comblée par interpolation dans le jeu d'entraînement n'a aucune mesure
    (taux_couverture = 0) : en production, elle serait absente de gold."""
    site = faux_site()
    site.loc[76, "taux_couverture"] = 0.0
    df = construire_variables(site, SANS_NORMALISATION, 24)
    assert pd.isna(df.loc[100, "lag_24h"])
    assert df.loc[100, "moyenne_24h"] == sum(range(53, 76)) / 23


def test_moyennes_par_site_sur_les_heures_mesurees():
    site = faux_site(nb_heures=4)
    site.loc[3, "taux_couverture"] = 0.0
    assert moyennes_par_site(site)["SITE001"] == 1.0


def test_sites_du_modele_pris_dans_les_moyennes():
    """La liste des sites est enregistrée avec le modèle (ses moyennes), pas recopiée
    dans le code."""
    moyennes = pd.Series({"SITE001": 1.0, "SITE042": 1.0})
    df = construire_variables(faux_site("SITE042"), moyennes, 24)
    assert noms_variables(24, moyennes)[-2:] == ["site_SITE001", "site_SITE042"]
    assert df.loc[0, "site_SITE042"] == 1
    assert "site_SITE002" not in df.columns


@pytest.mark.parametrize(
    "debut",
    [
        pd.Timestamp("2024-01-05 10:37", tz="UTC"),
        pd.Timestamp("2024-01-05 10:00"),
    ],
)
def test_debut_des_previsions_controle(debut):
    with pytest.raises(ValueError, match="Début des prévisions"):
        ajouter_heures_a_prevoir(faux_site(), debut, 24)


def test_heures_a_prevoir_avec_l_historique_utile_seulement():
    historique = faux_site(nb_heures=1000)
    debut = historique["heure"].max() + pd.Timedelta(hours=1)
    df = ajouter_heures_a_prevoir(historique, debut, 24)
    # 28 jours d'historique (672 h) + 24 heures à prévoir
    assert len(df) == 672 + 24
    df = construire_variables(df, SANS_NORMALISATION, 24)
    futur = df[df["heure"] >= debut].reset_index(drop=True)
    assert futur.loc[0, "lag_28j"] == 1000 - 672


def test_pas_plus_d_heures_a_prevoir_que_l_horizon():
    historique = faux_site()
    debut = historique["heure"].max() + pd.Timedelta(hours=1)
    # 48 heures avec le modèle à 24 h : les 24 dernières n'auraient pas de lag connu
    with pytest.raises(ValueError, match="Horizon"):
        ajouter_heures_a_prevoir(historique, debut, 48)


def test_historique_en_retard_refuse():
    historique = faux_site()
    debut = historique["heure"].max() + pd.Timedelta(hours=4)
    with pytest.raises(ValueError, match="en retard.*SITE001"):
        ajouter_heures_a_prevoir(historique, debut, 24)


def test_site_sans_donnee_recente_ne_disparait_pas():
    """Un site muet depuis plus de 28 jours est nommé dans l'erreur, au lieu de
    disparaître des prévisions."""
    a_jour = faux_site("SITE001", nb_heures=1000)
    muet = faux_site("SITE002", nb_heures=100)
    debut = a_jour["heure"].max() + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="SITE002") as erreur:
        ajouter_heures_a_prevoir(pd.concat([a_jour, muet]), debut, 24)
    assert "SITE001" not in str(erreur.value)


def test_derniere_heure_sans_mesure_compte_comme_retard():
    historique = faux_site()
    historique.loc[199, "taux_couverture"] = 0.0
    debut = historique["heure"].max() + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="en retard"):
        ajouter_heures_a_prevoir(historique, debut, 24)


def test_site_sans_moyenne_valable_ecarte_des_le_depart():
    """Sans moyenne valable, le site ne peut pas être prévu : il n'a pas de colonne
    site_… dans le modèle."""
    deux_sites = pd.concat([faux_site("SITE001"), faux_site("SITE002")])
    deux_sites.loc[deux_sites["id_site"] == "SITE002", "moyenne_kw"] = 0.0
    moyennes = moyennes_par_site(deux_sites)
    assert list(moyennes.index) == ["SITE001"]
    assert "site_SITE002" not in noms_variables(24, moyennes)
