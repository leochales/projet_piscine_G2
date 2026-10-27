import numpy as np
import pandas as pd
import pytest

from model import entrainement
from model.baseline import ajouter_baselines
from model.entrainement import (
    REFERENCE,
    ajouter_previsions,
    entrainer,
    entrainer_horizon,
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
    d = ajouter_previsions(lignes, modeles, noms, moyennes, "validation")
    assert (d["jeu"] == "validation").all()
    colonnes = [REFERENCE, "baseline_veille", *modeles]
    assert d[colonnes].notna().all().all()


@pytest.mark.parametrize("horizon", [24, 168])
def test_bat_la_reference_sur_un_motif_simple(horizon):
    """Rythme par semaine plus du bruit : la référence recopie le bruit de la semaine
    précédente, le modèle apprend le rythme."""
    df = faux_jeu()
    r = entrainer_horizon(df, moyennes_entrainement(df), horizon)
    # Choix fait sur la validation : le modèle retenu y a le plus petit WAPE
    wape_validation = r.validation.loc[["ridge", "random_forest"], "WAPE_%"]
    assert r.meilleur == wape_validation.idxmin()
    # Sur le test, le modèle retenu fait mieux que la référence, sur chaque site
    assert list(r.test.index) == ["baseline_veille", REFERENCE, r.meilleur]
    assert r.test.loc[r.meilleur, "WAPE_%"] < r.test.loc[REFERENCE, "WAPE_%"]
    assert (r.par_site[r.meilleur] < r.par_site[REFERENCE]).all()
    assert list(r.par_site.index) == ["SITE001", "SITE002"]
