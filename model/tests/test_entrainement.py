import logging
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from model import entrainement
from model.baseline import ajouter_baselines
from model.entrainement import (
    REFERENCE,
    ajouter_previsions,
    code_sortie,
    entrainer,
    entrainer_horizon,
    entrainer_modele_final,
    garder_sites_connus,
    lire_empreinte,
    main,
    preparer,
    prevoir_kwh,
)
from model.features import moyennes_par_site, noms_variables

NB_JOURS = 63


def faux_jeu(bruit: float = 0.1) -> pd.DataFrame:
    """Deux sites sur 9 semaines, au format du jeu du ticket 93 : un rythme par jour
    et par semaine (bureaux ouverts de 8 h à 18 h en semaine), plus un bruit
    aléatoire. Découpage chronologique 70 / 15 / 15, comme le ticket 93."""
    rng = np.random.default_rng(0)
    heures = pd.date_range("2024-01-01", periods=NB_JOURS * 24, freq="h", tz="UTC")
    ouvert = (heures.dayofweek < 5) & (heures.hour >= 8) & (heures.hour < 18)
    lignes = []
    for site, taille in [("SITE001", 100.0), ("SITE002", 1000.0)]:
        conso = taille * np.where(ouvert, 1.6, 0.6)
        conso = conso * (1 + bruit * rng.standard_normal(len(heures)))
        lignes.append(
            pd.DataFrame(
                {
                    "id_site": site,
                    "heure": heures,
                    "moyenne_kw": conso,
                    "taux_couverture": 1.0,
                    "consommation_kwh_brute": conso,
                }
            )
        )
    df = pd.concat(lignes, ignore_index=True)
    debut_validation = heures[int(len(heures) * 0.70)]
    debut_test = heures[int(len(heures) * 0.85)]
    df["jeu"] = "entrainement"
    df.loc[df["heure"] >= debut_validation, "jeu"] = "validation"
    df.loc[df["heure"] >= debut_test, "jeu"] = "test"
    return ajouter_baselines(df)


def moyennes_entrainement(df: pd.DataFrame) -> pd.Series:
    return moyennes_par_site(df[df["jeu"] == "entrainement"])


class ModeleEspion:
    """Faux modèle : retient les lignes reçues à l'entraînement et prévoit toujours
    1, c'est-à-dire la moyenne du site."""

    def fit(self, X, y):
        self.lignes_vues = X.index
        return self

    def predict(self, X):
        return np.ones(len(X))


def test_preparer_garde_les_heures_mesurees_meme_incompletes():
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    df.loc[500, "taux_couverture"] = 0.0
    lignes = preparer(df, moyennes, 24)
    # L'heure sans mesure n'est ni apprise ni évaluée
    assert 500 not in lignes.index
    # Les premières heures, sans lag de 28 jours, sont gardées
    assert 0 in lignes.index
    assert pd.isna(lignes.loc[0, "lag_28j"])


def test_entrainement_sur_le_jeu_d_entrainement_seulement(monkeypatch):
    espion = ModeleEspion()
    monkeypatch.setattr(entrainement, "creer_modeles", lambda: {"espion": espion})
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    lignes = preparer(df, moyennes, 24)
    entrainer(lignes, noms_variables(24, moyennes))
    jeux_vus = lignes.loc[espion.lignes_vues, "jeu"]
    assert (jeux_vus == "entrainement").all()
    assert len(jeux_vus) == (lignes["jeu"] == "entrainement").sum()


def test_prevision_remise_en_kwh():
    """Le modèle prévoit conso_norm : 1 veut dire « la moyenne du site »."""
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    lignes = preparer(df, moyennes, 24)
    prevision = prevoir_kwh(
        ModeleEspion(), lignes, noms_variables(24, moyennes), moyennes
    )
    attendu = lignes["id_site"].map(moyennes)
    pd.testing.assert_series_equal(prevision, attendu, check_names=False)


def test_heures_avec_variable_manquante_prevues():
    """Les deux modèles prévoient une heure dont un lag manque (panne passée), comme
    il faudra le faire en production."""
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    # Une journée de panne en validation : ses lags manqueront 24 h plus tard
    panne = (df["jeu"] == "validation") & (df["heure"].dt.day == 15)
    panne &= df["heure"].dt.month == 2
    df.loc[panne, "taux_couverture"] = 0.0
    lignes = preparer(df, moyennes, 24)
    noms = noms_variables(24, moyennes)
    modeles = entrainer(lignes, noms)
    incompletes = lignes[lignes[noms].isna().any(axis=1)]
    assert len(incompletes) > 0
    for modele in modeles.values():
        assert prevoir_kwh(modele, incompletes, noms, moyennes).notna().all()


def test_modeles_et_reference_notes_sur_les_memes_heures():
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    lignes = preparer(df, moyennes, 24)
    noms = noms_variables(24, moyennes)
    modeles = entrainer(lignes, noms)
    d = ajouter_previsions(lignes, modeles, noms, moyennes, "validation", 24)
    assert (d["jeu"] == "validation").all()
    colonnes = [REFERENCE, "baseline_veille", *modeles]
    assert d[colonnes].notna().all().all()


def test_a_7_jours_la_veille_ne_compte_pas():
    """À 7 jours, la veille n'est pas connue au moment de prévoir : elle n'est ni
    affichée, ni utilisée pour écarter des heures."""
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    veille_manquante = (df["jeu"] == "validation") & (df["id_site"] == "SITE001")
    df.loc[veille_manquante, "baseline_veille"] = np.nan
    lignes = preparer(df, moyennes, 168)
    noms = noms_variables(168, moyennes)
    d = ajouter_previsions(lignes, {}, noms, moyennes, "validation", 168)
    assert (d["id_site"] == "SITE001").any()
    r = entrainer_horizon(df, moyennes, 168)
    assert "baseline_veille" not in r.test.index
    assert "baseline_veille" not in r.validation.index


@pytest.mark.parametrize("horizon", [24, 168])
def test_bat_la_reference_sur_un_motif_simple(horizon):
    """Rythme par semaine plus du bruit : la référence recopie le bruit de la semaine
    précédente, le modèle apprend le rythme."""
    df = faux_jeu()
    r = entrainer_horizon(df, moyennes_entrainement(df), horizon)
    # Choix fait sur la validation : le modèle retenu y a le plus petit WAPE
    wape_validation = r.validation.loc[["ridge", "random_forest"], "WAPE_%"]
    assert r.meilleur == wape_validation.idxmin()
    # Règle de SMARTOPS-30, décidée sur la validation
    assert r.bat_reference
    assert r.bat_reference_test
    assert (
        r.validation.loc[r.meilleur, "WAPE_%"] < r.validation.loc[REFERENCE, "WAPE_%"]
    )
    # Sur le test, le modèle retenu fait aussi mieux que la référence, sur chaque site
    references = ["baseline_veille", REFERENCE] if horizon == 24 else [REFERENCE]
    assert list(r.test.index) == [*references, r.meilleur]
    assert r.test.loc[r.meilleur, "WAPE_%"] < r.test.loc[REFERENCE, "WAPE_%"]
    assert (r.par_site[r.meilleur] < r.par_site[REFERENCE]).all()
    assert list(r.par_site.index) == ["SITE001", "SITE002"]


def test_modele_qui_ne_bat_pas_la_reference_signale():
    """Consommation qui se répète à l'identique chaque semaine : la référence est
    parfaite, le modèle ne peut pas faire mieux. La règle de SMARTOPS-30 le signale."""
    df = faux_jeu(bruit=0.0)
    r = entrainer_horizon(df, moyennes_entrainement(df), 24)
    assert not r.bat_reference


def test_site_sans_heure_d_entrainement_ecarte_sans_bloquer():
    df = faux_jeu()
    # SITE002 mis en service après la date de coupure : rien dans l'entraînement
    df = df[~((df["id_site"] == "SITE002") & (df["jeu"] == "entrainement"))]
    moyennes = moyennes_entrainement(df)
    gardes = garder_sites_connus(df, moyennes)
    assert set(gardes["id_site"]) == {"SITE001"}
    entrainer_horizon(gardes, moyennes, 24)


def test_main_moyennes_sur_l_entrainement_seulement(monkeypatch, tmp_path):
    """Le script complet, sur un faux jeu : les moyennes par site ne voient que
    l'entraînement, sinon le test serait faussé (fuite de données)."""
    chemin = tmp_path / "dataset.parquet"
    faux_jeu().drop(columns=["baseline_veille", REFERENCE]).to_parquet(chemin)
    jeux_vus = []

    def moyennes_espion(train):
        jeux_vus.extend(train["jeu"].unique())
        return moyennes_par_site(train)

    monkeypatch.setattr(entrainement, "moyennes_par_site", moyennes_espion)
    resultats = main(["--chemin", str(chemin), "--sans-mlflow"])
    assert jeux_vus == ["entrainement"]
    assert len(resultats) == 2
    assert all(r.bat_reference for r in resultats)


def test_main_exige_l_adresse_de_mlflow(monkeypatch, tmp_path):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    with pytest.raises(SystemExit):
        main(["--chemin", str(tmp_path / "dataset.parquet")])


def test_modele_final_entraine_sur_toutes_les_donnees(monkeypatch):
    """Une fois le choix fait, le modèle de production apprend aussi la validation et
    le test, avec des moyennes par site recalculées sur toutes les données."""
    espion = ModeleEspion()
    monkeypatch.setattr(entrainement, "creer_modeles", lambda: {"espion": espion})
    df = faux_jeu()
    modele, moyennes = entrainer_modele_final(df, 24, "espion")
    assert modele is espion
    jeux_vus = set(df.loc[espion.lignes_vues, "jeu"])
    assert jeux_vus == {"entrainement", "validation", "test"}
    pd.testing.assert_series_equal(moyennes, moyennes_par_site(df))


def test_lire_empreinte(tmp_path):
    chemin = tmp_path / "dataset.parquet"
    assert lire_empreinte(chemin) is None
    (tmp_path / "rapport_qualite.json").write_text('{"empreinte": "abc123"}')
    assert lire_empreinte(chemin) == "abc123"


def test_main_refuse_d_enregistrer_sans_empreinte(monkeypatch, tmp_path):
    """Un modèle enregistré doit être relié à son jeu d'entraînement : sans
    rapport_qualite.json, la commande s'arrête avant d'entraîner."""
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow-inutile")
    with pytest.raises(SystemExit):
        main(["--chemin", str(tmp_path / "dataset.parquet")])


def test_remplace_production():
    """Le modèle prend l'alias production s'il bat la référence, et la version en
    production quand il y en a une."""
    df = faux_jeu()
    r = entrainer_horizon(df, moyennes_entrainement(df), 24)
    assert r.bat_production is None
    assert r.remplace_production
    assert replace(r, bat_production=True).remplace_production
    assert not replace(r, bat_production=False).remplace_production
    # La référence passe d'abord : aucune comparaison ne rattrape un modèle refusé
    assert not replace(r, bat_reference=False, bat_production=True).remplace_production


def test_code_sortie_en_erreur_si_le_modele_ne_bat_pas_la_reference(caplog):
    df = faux_jeu()
    bon = entrainer_horizon(df, moyennes_entrainement(df), 24)
    mauvais = replace(bon, bat_reference=False)
    assert code_sortie([bon, bon]) == 0
    with caplog.at_level(logging.ERROR):
        assert code_sortie([bon, mauvais]) == 1
    # L'horizon en échec est dans les logs : 24 h est le premier, 7 jours le second
    assert "168 h" in caplog.text
    # Rien à entraîner (pas assez de mesures) n'est pas une erreur
    assert code_sortie([]) == 0


def test_moins_bon_que_la_production_n_est_pas_une_erreur():
    df = faux_jeu()
    bon = entrainer_horizon(df, moyennes_entrainement(df), 24)
    garde = replace(bon, bat_production=False)
    assert code_sortie([garde, garde]) == 0


def test_sites_ecartes_signales_dans_les_logs(caplog):
    df = faux_jeu()
    df = df[~((df["id_site"] == "SITE002") & (df["jeu"] == "entrainement"))]
    with caplog.at_level(logging.WARNING):
        garder_sites_connus(df, moyennes_entrainement(df))
    assert "SITE002" in caplog.text


def test_main_ecrit_dans_les_logs_pas_dans_la_console(tmp_path, caplog, capsys):
    chemin = tmp_path / "dataset.parquet"
    faux_jeu().drop(columns=["baseline_veille", REFERENCE]).to_parquet(chemin)
    with caplog.at_level(logging.INFO):
        main(["--chemin", str(chemin), "--sans-mlflow"])
    messages = [r.getMessage() for r in caplog.records]
    assert any("horizon 24 h : modèle retenu" in m for m in messages)
    assert any("horizon 168 h : modèle retenu" in m for m in messages)
    assert capsys.readouterr().out == ""


def test_sans_test_le_choix_reste_le_meme():
    """Le réentraînement note le modèle sur son examen : il saute le test, mais choisit
    et juge le modèle de la même façon sur la validation."""
    df = faux_jeu()
    moyennes = moyennes_entrainement(df)
    avec = entrainer_horizon(df, moyennes, 24)
    sans = entrainer_horizon(df, moyennes, 24, avec_test=False)
    assert sans.meilleur == avec.meilleur
    assert sans.bat_reference == avec.bat_reference
    pd.testing.assert_frame_equal(sans.validation, avec.validation)
    assert sans.test.empty
    assert sans.par_site.empty
    assert sans.heures_test == 0


def test_journaliser_sans_test(caplog):
    df = faux_jeu()
    sans = entrainer_horizon(df, moyennes_entrainement(df), 24, avec_test=False)
    with caplog.at_level(logging.INFO):
        entrainement.journaliser(24, sans)
    assert "sur la validation" in caplog.text
    assert "sur le test" not in caplog.text
