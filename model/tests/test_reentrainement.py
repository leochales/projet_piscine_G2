from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from model import reentrainement, registre
from model.baseline import ajouter_baselines
from model.entrainement import (
    REFERENCE,
    entrainer_horizon,
    entrainer_modele_final,
)
from model.features import moyennes_par_site
from model.reentrainement import (
    GOLD_MIN,
    decouper,
    evaluer_sur_l_examen,
    fusionner,
    lire_gold,
    main,
    reentrainer,
)
from model.tests.test_entrainement import faux_jeu

# Stockage en fichiers de MLflow (test seulement) : codecs.open, déprécié en Python 3.14
pytestmark = pytest.mark.filterwarnings("ignore:codecs.open:DeprecationWarning")


def faux_csv(bruit: float = 0.1) -> pd.DataFrame:
    """Le jeu CSV tel que model.dataset l'écrit : sans les prévisions de référence."""
    return faux_jeu(bruit).drop(columns=["baseline_veille", REFERENCE])


def faux_gold(
    debut: str = "2025-01-01", jours: int = 12, bruit: float = 0.1
) -> pd.DataFrame:
    """Heures de gold après le CSV (63 jours en 2024), avec le même rythme : bureaux
    ouverts de 8 h à 18 h en semaine. Le trou entre les deux est voulu : il existe
    aussi dans le projet."""
    rng = np.random.default_rng(1)
    heures = pd.date_range(debut, periods=jours * 24, freq="h", tz="UTC")
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
                    "consommation_kwh": conso,
                    "pic_kw": conso * 1.2,
                    "moyenne_kw": conso,
                    "nb_mesures": 60,
                    "nb_imputees": 0,
                    "taux_couverture": 1.0,
                    "heure_complete": True,
                    "consommation_kwh_brute": conso,
                    "methode_imputation": "none",
                }
            )
        )
    return pd.concat(lignes, ignore_index=True)


class ModeleConstant:
    """Faux modèle qui prévoit toujours la même consommation normalisée : 5 veut dire
    « 5 fois la moyenne du site », très loin de la réalité."""

    def __init__(self, valeur: float = 5.0):
        self.valeur = valeur

    def predict(self, X):
        return np.full(len(X), self.valeur)


def jeu_pret() -> pd.DataFrame:
    return ajouter_baselines(decouper(fusionner(faux_csv(), faux_gold())))


def test_lire_gold_au_format_du_jeu():
    class FausseConnexion:
        def __init__(self, lignes):
            self.lignes = lignes

        def execute(self, requete):
            return self

        def all(self):
            return self.lignes

    paris = timezone(timedelta(hours=2))
    conn = FausseConnexion(
        [
            # PostgreSQL rend du NUMERIC en Decimal, et l'heure dans le fuseau de la session
            (
                "SITE001",
                datetime(2026, 10, 28, 12, tzinfo=paris),
                Decimal("10.5"),
                Decimal("12.0"),
                Decimal("10.5"),
                60,
                0,
                Decimal("1.0"),
                True,
            ),
            # Heure sans aucune mesure
            (
                "SITE001",
                datetime(2026, 10, 28, 13, tzinfo=paris),
                None,
                None,
                None,
                0,
                0,
                Decimal(0),
                True,
            ),
        ]
    )
    gold = lire_gold(conn)
    assert gold["heure"].iloc[0] == pd.Timestamp("2026-10-28 10:00", tz="UTC")
    assert gold["moyenne_kw"].dtype == float
    assert gold["consommation_kwh_brute"].iloc[0] == 10.5
    # Une heure sans mesure garde une consommation vide, comme dans le jeu CSV
    assert pd.isna(gold["consommation_kwh_brute"].iloc[1])


def test_fusionner_ne_garde_que_gold_apres_le_csv():
    csv = faux_csv()
    # Gold qui commence avant la fin du CSV : les heures communes ne sont pas doublées
    gold = faux_gold(debut="2024-03-01", jours=10)
    df = fusionner(csv, gold)
    assert not df.duplicated(["id_site", "heure"]).any()
    assert df["heure"].max() == gold["heure"].max()
    # Les heures du CSV sont celles du CSV
    avant = df[df["heure"] <= csv["heure"].max()]
    assert len(avant) == len(csv)


def test_decouper_les_7_derniers_jours_sont_l_examen():
    df = fusionner(faux_csv(), faux_gold())
    df = decouper(df)
    examen = df[df["jeu"] == "test"]
    assert examen["heure"].nunique() == 7 * 24
    assert examen["heure"].max() == df["heure"].max()
    # Chronologique, sans recouvrement, et les mêmes heures pour tous les sites
    fin = df.groupby("jeu")["heure"].agg(["min", "max"])
    assert fin.loc["entrainement", "max"] < fin.loc["validation", "min"]
    assert fin.loc["validation", "max"] < fin.loc["test", "min"]
    assert examen.groupby("id_site").size().nunique() == 1
    # Aucun jeu vide : l'entraînement garde l'essentiel du CSV
    assert (df["jeu"] == "entrainement").sum() > (df["jeu"] == "validation").sum()


def test_pas_assez_de_gold_ne_reentraine_rien(client):
    # 5 jours de mesures : moins que l'examen (7 jours) plus un jour
    assert len(reentrainer(faux_csv(), faux_gold(jours=5), "abc")) == 0
    assert len(reentrainer(faux_csv(), faux_gold().iloc[0:0], "abc")) == 0
    assert len(client.search_registered_models()) == 0
    assert GOLD_MIN == pd.Timedelta(days=8)


def test_premier_reentrainement_enregistre_sans_comparaison(client):
    """Sans version en production, rien à comparer : le modèle qui bat la référence
    est enregistré."""
    resultats = reentrainer(faux_csv(), faux_gold(), "abc")
    assert len(resultats) == 2
    for r in resultats:
        assert r.bat_production is None
        assert r.remplace_production
        # Les scores du test sont ceux de l'examen : le candidat, les références
        assert r.meilleur in r.test.index
        assert REFERENCE in r.test.index
    production = registre.charger(24)
    assert production.version == "prevision-conso-24h/1"
    run = client.get_run(
        client.get_model_version_by_alias(
            registre.nom_modele(24), registre.ALIAS
        ).run_id
    )
    # Le run garde de quels jeux vient le modèle
    assert run.data.params["empreinte_jeu"] == "abc+gold:2025-01-12T23"
    assert run.data.tags["bat_production"] == "sans_production"


def test_une_meilleure_version_prend_l_alias(client, monkeypatch):
    reentrainer(faux_csv(), faux_gold(), "abc")
    moyennes = pd.Series({"SITE001": 100.0, "SITE002": 1000.0})
    mauvaise = registre.ModeleProduction(ModeleConstant(), moyennes, "mauvais/1")
    monkeypatch.setattr(reentrainement, "charger_production", lambda horizon: mauvaise)
    resultats = reentrainer(faux_csv(), faux_gold(), "abc")
    for r in resultats:
        assert r.bat_production is True
        assert "production" in r.test.index
        assert r.test.loc[r.meilleur, "WAPE_%"] < r.test.loc["production", "WAPE_%"]
    for horizon in (24, 168):
        version = client.get_model_version_by_alias(
            registre.nom_modele(horizon), registre.ALIAS
        )
        # MLflow 3 donne le numéro de version en entier
        assert str(version.version) == "2"
        run = client.get_run(version.run_id)
        assert run.data.tags["bat_production"] == "true"
        assert "test_production_WAPE" in run.data.metrics


def test_garde_la_production_si_le_candidat_est_moins_bon(client, monkeypatch):
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24)
    bonne, moyennes_bonne = entrainer_modele_final(df, 24, r.meilleur)
    production = registre.ModeleProduction(bonne, moyennes_bonne, "bon/1")
    monkeypatch.setattr(
        reentrainement, "charger_production", lambda horizon: production
    )
    # Un candidat très mauvais, face à une production qui connaît le rythme
    monkeypatch.setattr(
        reentrainement,
        "entrainer_modele_final",
        lambda *args: (ModeleConstant(), moyennes_bonne),
    )
    evalue = evaluer_sur_l_examen(df, r, 24)
    assert evalue.bat_production is False
    assert not evalue.remplace_production
    assert (
        evalue.test.loc["production", "WAPE_%"] < evalue.test.loc[r.meilleur, "WAPE_%"]
    )


def test_candidat_et_production_notes_sur_les_memes_sites(monkeypatch):
    """Un site que la production ne connaît pas (mis en service après elle) ne compte pas
    dans la comparaison, pour ne pas fausser le score de l'un des deux."""
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24)
    ancienne = moyennes.loc[["SITE001"]]
    production = registre.ModeleProduction(ModeleConstant(1.0), ancienne, "ancien/1")
    monkeypatch.setattr(
        reentrainement, "charger_production", lambda horizon: production
    )
    evalue = evaluer_sur_l_examen(df, r, 24)
    assert list(evalue.par_site.index) == ["SITE001"]


def test_examen_trop_court_garde_la_production(monkeypatch):
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24)
    monkeypatch.setattr(reentrainement, "MIN_HEURES_EXAMEN", 10**6)
    production = registre.ModeleProduction(ModeleConstant(), moyennes, "x/1")
    monkeypatch.setattr(
        reentrainement, "charger_production", lambda horizon: production
    )
    # Trop peu d'heures pour comparer à la production : on ne la remplace pas
    assert evaluer_sur_l_examen(df, r, 24).bat_production is False
    # Sans production, il n'y a rien à garder
    monkeypatch.setattr(reentrainement, "charger_production", lambda horizon: None)
    assert evaluer_sur_l_examen(df, r, 24).bat_production is None


def test_main_exige_mlflow_et_l_empreinte(monkeypatch, tmp_path):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    with pytest.raises(SystemExit):
        main(["--chemin", str(tmp_path / "dataset.parquet")])
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow-inutile")
    with pytest.raises(SystemExit):
        main(["--chemin", str(tmp_path / "dataset.parquet")])


def test_main_lit_gold_et_enregistre(client, monkeypatch, tmp_path):
    class FauxMoteur:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *erreur):
            return False

    chemin = tmp_path / "dataset.parquet"
    faux_csv().to_parquet(chemin)
    (tmp_path / "rapport_qualite.json").write_text('{"empreinte": "abc123"}')
    monkeypatch.setattr(reentrainement, "get_engine", lambda: FauxMoteur())
    monkeypatch.setattr(reentrainement, "lire_gold", lambda conn: faux_gold())
    resultats = main(["--chemin", str(chemin)])
    assert len(resultats) == 2
    assert registre.charger(168).version == "prevision-conso-168h/1"


def test_les_messages_passent_par_les_logs(client, caplog, capsys):
    """Visibles dans Grafana : rien sur la console, tout dans les logs."""
    with caplog.at_level("INFO"):
        reentrainer(faux_csv(), faux_gold(), "abc")
    messages = [r.getMessage() for r in caplog.records]
    assert any("horizon 24 h : modèle retenu" in m for m in messages)
    assert any("version 1 en production" in m for m in messages)
    assert capsys.readouterr().out == ""
