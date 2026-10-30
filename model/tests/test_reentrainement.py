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

# Dernière heure du faux gold par défaut : 14 jours à partir du 2025-01-01
FIN_FAUX_GOLD = pd.Timestamp("2025-01-14 23:00", tz="UTC")


def faux_csv(bruit: float = 0.1) -> pd.DataFrame:
    """Le jeu CSV tel que model.dataset l'écrit : sans les prévisions de référence."""
    return faux_jeu(bruit).drop(columns=["baseline_veille", REFERENCE])


def faux_gold(
    debut: str = "2025-01-01", jours: int = 14, bruit: float = 0.1
) -> pd.DataFrame:
    """Heures de gold après le CSV (63 jours en 2024), avec le même rythme : bureaux
    ouverts de 8 h à 18 h en semaine. Le trou entre les deux est voulu : il existe
    aussi dans le projet, et il est plus long que l'historique utile (28 jours).
    Par défaut 14 jours, le minimum du réentraînement."""
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

    def ligne(heure, moyenne, couverture):
        # PostgreSQL rend du NUMERIC en Decimal, et l'heure dans le fuseau de la session
        return (
            "SITE001",
            datetime(2026, 10, 28, heure, tzinfo=paris),
            moyenne,
            moyenne,
            moyenne,
            60,
            0,
            couverture,
            True,
        )

    conn = FausseConnexion(
        [
            ligne(12, Decimal("10.5"), Decimal("1.0")),
            # 80 % des minutes mesurées : le minimum, gardée
            ligne(13, Decimal("8.0"), Decimal("0.8")),
            # Une seule minute mesurée : écartée, comme une heure absente
            ligne(14, Decimal("3.0"), Decimal("0.0167")),
            # Aucune mesure
            ligne(15, None, Decimal(0)),
        ]
    )
    gold = lire_gold(conn)
    assert list(gold["heure"]) == [
        pd.Timestamp("2026-10-28 10:00", tz="UTC"),
        pd.Timestamp("2026-10-28 11:00", tz="UTC"),
    ]
    assert gold["moyenne_kw"].dtype == float
    # Comme dans le jeu CSV, la consommation brute est celle de l'heure
    assert list(gold["consommation_kwh_brute"]) == [10.5, 8.0]


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


def test_toutes_les_heures_de_l_examen_ont_leur_reference():
    """Avec 14 jours de gold, la semaine précédente de chaque heure de l'examen existe
    dans gold : l'examen porte sur 7 jours, pas sur un seul."""
    df = jeu_pret()
    examen = df[df["jeu"] == "test"]
    assert examen[REFERENCE].notna().all()
    assert examen["baseline_veille"].notna().all()
    # Avec 8 jours, seul le dernier jour aurait sa référence
    court = ajouter_baselines(decouper(fusionner(faux_csv(), faux_gold(jours=8))))
    assert court.loc[court["jeu"] == "test", REFERENCE].notna().sum() < len(examen) / 4


def test_pas_assez_de_gold_ne_reentraine_rien(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("rien ne doit être enregistré")

    monkeypatch.setattr(registre, "enregistrer", interdit)
    assert GOLD_MIN == pd.Timedelta(days=14)
    # 13 jours : la semaine d'avant l'examen serait incomplète
    assert reentrainer(faux_csv(), faux_gold(jours=13), "abc") == []
    assert reentrainer(faux_csv(), faux_gold().iloc[0:0], "abc") == []


def test_reentrainement_complet_sans_mlflow(monkeypatch):
    """Le réentraînement de bout en bout, avec un faux enregistrement : sans version en
    production, les deux horizons sont enregistrés, avec la fin de leurs données."""
    appels = []

    def faux_enregistrer(
        resultat, horizon, reglages, empreinte, final, fin_donnees=None
    ):
        appels.append((horizon, resultat, empreinte, final, fin_donnees))
        return "1"

    monkeypatch.setattr(registre, "enregistrer", faux_enregistrer)
    monkeypatch.setattr(reentrainement, "charger_production", lambda horizon: None)
    resultats = reentrainer(faux_csv(), faux_gold(), "abc")
    assert [a[0] for a in appels] == [24, 168]
    assert len(resultats) == 2
    for _, r, empreinte, final, fin_donnees in appels:
        assert r.bat_production is None
        assert r.remplace_production
        # Le modèle enregistré est réentraîné sur toutes les données
        assert final is not None
        assert fin_donnees == FIN_FAUX_GOLD
        assert empreinte == "abc+gold:2025-01-14T23"
        # Les scores du test sont ceux de l'examen : 7 jours, 2 sites, tous avec référence
        assert r.meilleur in r.test.index
        assert REFERENCE in r.test.index
        assert r.heures_test == 2 * 7 * 24
        assert r.sans_reference == 0


def test_modele_refuse_n_est_pas_note_sur_l_examen(monkeypatch):
    """Consommation qui se répète à l'identique chaque semaine : la référence est
    parfaite. Le modèle est refusé sur la validation, sans calcul de test ni comparaison
    avec la production."""
    appels = []

    def faux_enregistrer(*args, **kwargs):
        appels.append(kwargs.get("fin_donnees"))

    def comparaison_interdite(horizon):
        raise AssertionError("inutile de comparer un modèle refusé")

    monkeypatch.setattr(registre, "enregistrer", faux_enregistrer)
    monkeypatch.setattr(reentrainement, "charger_production", comparaison_interdite)
    resultats = reentrainer(faux_csv(bruit=0.0), faux_gold(bruit=0.0), "abc")
    assert all(not r.bat_reference for r in resultats)
    assert all(r.test.empty for r in resultats)
    assert all(not r.remplace_production for r in resultats)
    assert len(appels) == 2


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
    # Le run garde de quels jeux vient le modèle, et jusqu'à quelle heure
    assert run.data.params["empreinte_jeu"] == "abc+gold:2025-01-14T23"
    assert pd.Timestamp(run.data.params["fin_donnees"]) == FIN_FAUX_GOLD
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


def test_garde_la_production_si_le_candidat_est_moins_bon(monkeypatch):
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24, avec_test=False)
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


def test_heures_deja_vues_par_la_production_ne_sont_pas_notees(monkeypatch):
    """Réentraînement relancé dans la semaine : la production a déjà appris une partie
    de l'examen. Seules les heures après la fin de ses données sont notées."""
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24, avec_test=False)
    production = registre.ModeleProduction(
        ModeleConstant(1.0), moyennes, "x/1", run_id="run-x"
    )
    monkeypatch.setattr(
        reentrainement, "charger_production", lambda horizon: production
    )
    examen = df[df["jeu"] == "test"]

    # Production entraînée avant l'examen : toutes ses heures comptent
    avant = examen["heure"].min() - pd.Timedelta(days=1)
    monkeypatch.setattr(registre, "fin_des_donnees", lambda run_id: avant)
    tout = evaluer_sur_l_examen(df, r, 24)
    assert tout.heures_test == len(examen)

    # Relance en milieu de semaine : les 3 premiers jours, déjà vus, ne comptent pas
    fin = examen["heure"].min() + pd.Timedelta(days=3)
    monkeypatch.setattr(registre, "fin_des_donnees", lambda run_id: fin)
    apres = evaluer_sur_l_examen(df, r, 24)
    assert apres.heures_test == int((examen["heure"] > fin).sum())
    assert 0 < apres.heures_test < tout.heures_test
    # Ces heures écartées ne sont pas des heures « sans référence »
    assert apres.sans_reference == 0

    # Production qui a tout vu : rien à noter, elle est gardée
    monkeypatch.setattr(
        registre, "fin_des_donnees", lambda run_id: examen["heure"].max()
    )
    rien = evaluer_sur_l_examen(df, r, 24)
    assert rien.bat_production is False
    assert not rien.remplace_production


def test_candidat_et_production_notes_sur_les_memes_sites(monkeypatch):
    """Un site que la production ne connaît pas (mis en service après elle) ne compte pas
    dans la comparaison, pour ne pas fausser le score de l'un des deux. Ses heures ne
    sont pas non plus comptées comme « sans référence »."""
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24, avec_test=False)
    ancienne = moyennes.loc[["SITE001"]]
    production = registre.ModeleProduction(ModeleConstant(1.0), ancienne, "ancien/1")
    monkeypatch.setattr(
        reentrainement, "charger_production", lambda horizon: production
    )
    evalue = evaluer_sur_l_examen(df, r, 24)
    assert list(evalue.par_site.index) == ["SITE001"]
    assert evalue.heures_test == 7 * 24
    assert evalue.sans_reference == 0


def test_examen_trop_court_garde_la_production(monkeypatch):
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24, avec_test=False)
    monkeypatch.setattr(reentrainement, "MIN_HEURES_EXAMEN", 10**6)
    production = registre.ModeleProduction(ModeleConstant(), moyennes, "x/1")
    monkeypatch.setattr(
        reentrainement, "charger_production", lambda horizon: production
    )
    # Trop peu d'heures pour comparer à la production : on ne la remplace pas
    assert evaluer_sur_l_examen(df, r, 24).bat_production is False


def test_sans_production_un_examen_trop_court_n_empeche_pas_d_enregistrer(monkeypatch):
    """Rien à comparer : le premier modèle qui bat la référence est enregistré, même si
    l'examen est trop court pour être noté."""
    df = jeu_pret()
    moyennes = moyennes_par_site(df[df["jeu"] == "entrainement"])
    r = entrainer_horizon(df, moyennes, 24, avec_test=False)
    assert r.bat_reference
    monkeypatch.setattr(reentrainement, "MIN_HEURES_EXAMEN", 10**6)
    monkeypatch.setattr(reentrainement, "charger_production", lambda horizon: None)
    evalue = evaluer_sur_l_examen(df, r, 24)
    assert evalue.bat_production is None
    assert evalue.remplace_production


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
