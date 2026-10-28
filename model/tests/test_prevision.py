import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, RESOURCE_DOES_NOT_EXIST

from model import prevision, registre
from model.entrainement import entrainer_modele_final
from model.features import COLONNES_ENTREE
from model.prevision import (
    assembler,
    charger_production,
    debut_des_previsions,
    ecrire,
    generer,
    prevoir,
    sites_prevus,
)
from model.registre import ModeleProduction
from model.tests.test_entrainement import faux_jeu


@pytest.fixture(scope="module")
def jeu():
    return faux_jeu()


@pytest.fixture(scope="module")
def historique(jeu):
    """Historique au format de gold.consommation_horaire, jusqu'à la dernière heure."""
    return jeu[COLONNES_ENTREE]


@pytest.fixture(scope="module")
def debut(historique):
    return historique["heure"].max() + pd.Timedelta(hours=1)


def production(jeu, horizon: int, nom: str = "random_forest") -> ModeleProduction:
    modele, moyennes = entrainer_modele_final(jeu, horizon, nom)
    return ModeleProduction(modele, moyennes, f"prevision-conso-{horizon}h/1")


@pytest.fixture(scope="module")
def modeles(jeu):
    return {24: production(jeu, 24), 168: production(jeu, 168)}


@pytest.mark.parametrize(
    "maintenant",
    [
        datetime(2026, 10, 28, 10, 5, tzinfo=UTC),
        datetime(2026, 10, 28, 10, 59, tzinfo=UTC),
        # Sans fuseau : lu comme de l'UTC
        datetime(2026, 10, 28, 10, 5),
        # Même instant à Paris (UTC+1 en hiver)
        pd.Timestamp("2026-10-28 11:05", tz="Europe/Paris"),
    ],
)
def test_debut_a_l_heure_pleine_suivante(maintenant):
    assert debut_des_previsions(maintenant) == pd.Timestamp(
        "2026-10-28 11:00", tz="UTC"
    )


def test_prevision_avec_fourchette(historique, debut, modeles):
    p = prevoir(historique, modeles[24], debut, 24)
    assert list(p.columns) == prevision.COLONNES
    assert len(p) == 2 * 24
    assert p["heure_prevue"].min() == debut
    assert p["heure_prevue"].max() == debut + pd.Timedelta(hours=23)
    assert (p["version_modele"] == "prevision-conso-24h/1").all()
    # Contrainte de gold.prediction, et une vraie fourchette
    assert (p["consommation_basse_kwh"] <= p["consommation_prevue_kwh"]).all()
    assert (p["consommation_prevue_kwh"] <= p["consommation_haute_kwh"]).all()
    assert (p["consommation_haute_kwh"] > p["consommation_basse_kwh"]).all()
    # En kWh, à l'échelle de chaque site (SITE002 consomme 10 fois plus)
    par_site = p.groupby("id_site")["consommation_prevue_kwh"].mean()
    assert 5 < par_site["SITE002"] / par_site["SITE001"] < 20


def test_prevision_suit_le_rythme_des_bureaux(historique, debut, modeles):
    """Le jeu de test a des bureaux ouverts de 8 h à 18 h en semaine : la prévision
    d'une heure ouverte dépasse celle d'une heure fermée."""
    p = prevoir(historique, modeles[168], debut, 168)
    p = p[p["id_site"] == "SITE001"]
    heures = pd.DatetimeIndex(p["heure_prevue"])
    ouvert = (heures.dayofweek < 5) & (heures.hour >= 8) & (heures.hour < 18)
    conso = p["consommation_prevue_kwh"].to_numpy()
    assert conso[ouvert].mean() > 2 * conso[~ouvert].mean()


def test_ridge_sans_fourchette(jeu, historique, debut):
    p = prevoir(historique, production(jeu, 24, "ridge"), debut, 24)
    assert len(p) == 2 * 24
    assert p["consommation_basse_kwh"].isna().all()
    assert p["consommation_haute_kwh"].isna().all()
    assert (p["consommation_prevue_kwh"] >= 0).all()


def test_sites_inconnus_ou_en_retard_ecartes(historique, debut, modeles, caplog):
    inconnu = historique[historique["id_site"] == "SITE001"].assign(id_site="SITE009")
    # SITE002 : plus de mesure depuis 3 heures (capteur en panne)
    retard = (historique["id_site"] == "SITE002") & (
        historique["heure"] >= debut - pd.Timedelta(hours=3)
    )
    df = pd.concat([historique[~retard], inconnu], ignore_index=True)
    with caplog.at_level(logging.WARNING):
        gardes = sites_prevus(df, modeles[24], debut)
    assert set(gardes["id_site"]) == {"SITE001"}
    assert set(prevoir(df, modeles[24], debut, 24)["id_site"]) == {"SITE001"}
    # Chaque message nomme la version qui écarte le site
    messages = [r.getMessage() for r in caplog.records]
    assert any("prevision-conso-24h/1" in m and "SITE009" in m for m in messages)
    assert any("prevision-conso-24h/1" in m and "SITE002" in m for m in messages)


def test_site_actif_sans_aucune_mesure_signale(historique, debut, modeles, caplog):
    """Une panne de plus de 28 jours : lire_historique renvoie le site sur une ligne
    vide (LEFT JOIN). Il n'est pas prévu, mais l'avertissement le nomme."""
    sans_mesure = historique[historique["id_site"] != "SITE002"]
    ligne_vide = pd.DataFrame(
        {
            "id_site": ["SITE002"],
            "heure": pd.Series([pd.NaT], dtype=historique["heure"].dtype),
            "moyenne_kw": [np.nan],
            "taux_couverture": [np.nan],
        }
    )
    df = pd.concat([sans_mesure, ligne_vide], ignore_index=True)
    with caplog.at_level(logging.WARNING):
        p = prevoir(df, modeles[24], debut, 24)
    assert set(p["id_site"]) == {"SITE001"}
    assert any(
        "sans mesure" in r.getMessage() and "SITE002" in r.getMessage()
        for r in caplog.records
    )


class FakeResultat:
    def __init__(self, lignes):
        self.lignes = lignes

    def all(self):
        return self.lignes


def test_lire_historique_convertit_les_lignes_de_postgresql(debut):
    """Lignes telles que psycopg les renvoie : Decimal, heure dans un autre fuseau,
    et la ligne vide du LEFT JOIN pour un site actif sans mesure."""
    paris = timezone(timedelta(hours=1))
    heure = (debut - pd.Timedelta(hours=1)).to_pydatetime().astimezone(paris)

    class Connexion:
        def execute(self, sql, parametres):
            self.sql = str(sql)
            self.parametres = parametres
            return FakeResultat(
                [
                    ("SITE001", heure, Decimal("12.50"), Decimal("1.000")),
                    ("SITE002", None, None, None),
                ]
            )

    conn = Connexion()
    df = prevision.lire_historique(conn, debut)
    assert "LEFT JOIN gold.consommation_horaire" in conn.sql
    assert conn.parametres["debut"] == debut
    assert str(df["heure"].dt.tz) == "UTC"
    assert df.loc[0, "heure"] == debut - pd.Timedelta(hours=1)
    assert df["moyenne_kw"].tolist()[0] == 12.5
    assert pd.isna(df.loc[1, "heure"])
    assert pd.isna(df.loc[1, "moyenne_kw"])
    assert pd.isna(df.loc[1, "taux_couverture"])


def test_aucun_site_prevu(historique, debut, modeles):
    plus_tard = debut + pd.Timedelta(hours=5)
    p = prevoir(historique, modeles[24], plus_tard, 24)
    assert p.empty
    assert list(p.columns) == prevision.COLONNES


def test_24h_puis_7_jours(historique, debut, modeles):
    """Le modèle 24 h prévoit les 24 premières heures, le modèle 7 jours la suite :
    une seule prévision par site et par heure."""
    p = assembler(historique, modeles, debut)
    assert len(p) == 2 * 168
    assert not p.duplicated(["id_site", "heure_prevue"]).any()
    limite = debut + pd.Timedelta(hours=24)
    premieres = p[p["heure_prevue"] < limite]
    suivantes = p[p["heure_prevue"] >= limite]
    assert (premieres["version_modele"] == "prevision-conso-24h/1").all()
    assert (suivantes["version_modele"] == "prevision-conso-168h/1").all()


def test_sans_modele_24h_le_7_jours_prevoit_tout(historique, debut, modeles):
    p = assembler(historique, {24: None, 168: modeles[168]}, debut)
    assert len(p) == 2 * 168
    assert (p["version_modele"] == "prevision-conso-168h/1").all()


def test_site_inconnu_du_modele_24h_prevu_par_le_7_jours(historique, debut, modeles):
    """Versions de dates différentes : la version 24 h ne connaît pas SITE002, la
    version 7 jours si. SITE002 garde ses 24 premières heures, prévues à 7 jours."""
    ancienne_24h = ModeleProduction(
        PrevoirSansSite002(modeles[24].modele),
        modeles[24].moyennes.drop("SITE002"),
        "prevision-conso-24h/1",
    )
    p = assembler(historique, {24: ancienne_24h, 168: modeles[168]}, debut)
    assert len(p) == 2 * 168
    assert not p.duplicated(["id_site", "heure_prevue"]).any()
    site002 = p[p["id_site"] == "SITE002"]
    assert len(site002) == 168
    assert (site002["version_modele"] == "prevision-conso-168h/1").all()


class PrevoirSansSite002:
    """Modèle appris avec deux sites, présenté comme s'il n'en connaissait qu'un."""

    def __init__(self, modele):
        self.modele = modele

    def predict(self, X):
        return self.modele.predict(
            X.assign(site_SITE002=0)[self.modele.feature_names_in_]
        )


def test_sans_aucun_modele(historique, debut):
    p = assembler(historique, {24: None, 168: None}, debut)
    assert p.empty


def erreur_mlflow(code):
    def charger(horizon, cache=None):
        raise MlflowException("erreur", code)

    return charger


def test_pas_de_version_en_production(monkeypatch, caplog):
    monkeypatch.setattr(registre, "charger", erreur_mlflow(RESOURCE_DOES_NOT_EXIST))
    with caplog.at_level(logging.WARNING):
        assert charger_production(24) is None
    assert "prevision-conso-24h" in caplog.text


def test_mlflow_injoignable_arrete_le_job(monkeypatch):
    """Une panne de MLflow n'est pas « pas de modèle » : le job échoue, visible dans
    les logs, plutôt que de ne rien prévoir sans erreur."""
    monkeypatch.setattr(registre, "charger", erreur_mlflow(INTERNAL_ERROR))
    with pytest.raises(MlflowException):
        charger_production(24)


def test_cache_lu_dans_l_environnement(monkeypatch, tmp_path):
    vus = []
    monkeypatch.setattr(registre, "charger", lambda h, cache=None: vus.append(cache))
    monkeypatch.delenv("MODELE_CACHE_DIR", raising=False)
    charger_production(24)
    monkeypatch.setenv("MODELE_CACHE_DIR", str(tmp_path))
    charger_production(24)
    assert vus == [None, tmp_path]


# Stockage en fichiers de MLflow (test seulement) : codecs.open, déprécié en Python 3.14
@pytest.mark.filterwarnings("ignore:codecs.open:DeprecationWarning")
def test_version_absente_dans_mlflow(client):
    """Avec un vrai MLflow sans modèle enregistré (premier déploiement)."""
    assert charger_production(24) is None


class FakeConnection:
    def __init__(self):
        self.parametres = None

    def execute(self, sql, parametres=None):
        self.sql = str(sql)
        self.parametres = parametres


def test_ecrire_bornes_absentes_en_null(historique, debut, jeu):
    p = prevoir(historique, production(jeu, 24, "ridge"), debut, 24)
    conn = FakeConnection()
    ecrire(conn, p)
    assert "INSERT INTO gold.prediction" in conn.sql
    assert len(conn.parametres) == len(p)
    ligne = conn.parametres[0]
    assert ligne["consommation_basse_kwh"] is None
    assert ligne["consommation_haute_kwh"] is None
    assert ligne["id_site"] == "SITE001"
    assert ligne["heure_prevue"] == debut


def test_generer_sans_modele_ne_touche_pas_la_base(monkeypatch):
    monkeypatch.setattr(prevision, "charger_production", lambda horizon: None)

    def pas_de_base():
        raise AssertionError("la base ne doit pas être lue")

    monkeypatch.setattr(prevision, "get_engine", pas_de_base)
    assert generer() == 0


def test_generer_lit_et_ecrit_dans_une_transaction(
    monkeypatch, historique, debut, modeles
):
    conn = FakeConnection()

    class FakeEngine:
        @contextmanager
        def begin(self):
            yield conn

    monkeypatch.setattr(prevision, "get_engine", FakeEngine)
    monkeypatch.setattr(prevision, "charger_production", modeles.get)
    monkeypatch.setattr(prevision, "lire_historique", lambda c, d: historique)
    maintenant = (debut - pd.Timedelta(minutes=55)).to_pydatetime()
    assert generer(maintenant) == 2 * 168
    assert len(conn.parametres) == 2 * 168
    assert np.isfinite([l["consommation_prevue_kwh"] for l in conn.parametres]).all()
