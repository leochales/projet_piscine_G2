import logging
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, RESOURCE_DOES_NOT_EXIST

from model import prevision, registre
from model.entrainement import entrainer_modele_final
from model.features import COLONNES_ENTREE
from model.prevision import (
    HEURES_MIN_RATIO_SITE,
    ajouter_pics,
    assembler,
    charger_production,
    debut_des_previsions,
    ecrire,
    generer,
    prevoir,
    ratios_pic,
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
    """Garde chaque requête ; ``sql`` et ``parametres`` sont ceux de la dernière."""

    def __init__(self):
        self.parametres = None
        self.requetes = []

    def execute(self, sql, parametres=None):
        self.sql = str(sql)
        self.parametres = parametres
        self.requetes.append((self.sql, parametres))
        return FakeResultat([])

    def parametres_de(self, debut_sql: str):
        """Paramètres de la requête qui contient ``debut_sql``."""
        return next(p for sql, p in self.requetes if debut_sql in sql)


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
    # Pic non calculé : NULL, et pic_prevu faux (colonne NOT NULL)
    assert "pic_prevu_kw" in conn.sql
    assert ligne["pic_prevu_kw"] is None
    assert ligne["pic_bas_kw"] is None
    assert ligne["pic_prevu"] is False


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
    monkeypatch.setattr(
        prevision, "lire_pics", lambda c, d: pics_constants("SITE001", 2.0)
    )
    sites = pd.DataFrame(
        {"seuil_kw": [0.0, 0.0], "capacite_kw": [1e9, 1e9]},
        index=pd.Index(["SITE001", "SITE002"], name="id_site"),
    )
    monkeypatch.setattr(prevision, "lire_sites", lambda c: sites)
    maintenant = (debut - pd.Timedelta(minutes=55)).to_pydatetime()
    assert generer(maintenant) == 2 * 168
    lignes = conn.parametres_de("INSERT INTO gold.prediction")
    assert len(lignes) == 2 * 168
    assert np.isfinite([l["consommation_prevue_kwh"] for l in lignes]).all()
    # Pic prévu pour le site qui a un historique de pics, pas pour l'autre
    site001 = [l for l in lignes if l["id_site"] == "SITE001"]
    site002 = [l for l in lignes if l["id_site"] == "SITE002"]
    assert all(l["pic_prevu_kw"] is not None and l["pic_prevu"] for l in site001)
    assert all(l["pic_prevu_kw"] is None and l["pic_prevu"] is False for l in site002)
    # Puis, dans la même transaction, l'alerte de pic prévu de SITE001 (seuil nul)
    sql = [s for s, _ in conn.requetes]
    assert sql.index(
        next(s for s in sql if "INSERT INTO gold.alerte" in s)
    ) > sql.index(next(s for s in sql if "INSERT INTO gold.prediction" in s))
    alertes = conn.parametres_de("INSERT INTO gold.alerte")
    assert [a["id_site"] for a in alertes] == ["SITE001"]


# --- Pic de l'heure (SMARTOPS-104) ---


def pics(id_site: str, ratios_par_heure, jours: int = 2) -> pd.DataFrame:
    """Heures terminées de gold.consommation_horaire : ``jours`` jours de 24 heures,
    moyenne de 100 kW et pic de 100 × le rapport de l'heure de la journée."""
    heures = pd.date_range("2026-10-01", periods=24 * jours, freq="h", tz="UTC")
    ratio = np.array([ratios_par_heure(h) for h in heures.hour])
    return pd.DataFrame(
        {
            "id_site": id_site,
            "heure": heures,
            "pic_kw": 100 * ratio,
            "moyenne_kw": 100.0,
        }
    )


def pics_constants(id_site: str, ratio: float) -> pd.DataFrame:
    return pics(id_site, lambda heure: ratio)


def test_ratio_par_heure_de_la_journee_sinon_du_site():
    # 3 jours : 8 h a 3 mesures (rapport 2), les autres heures en ont aussi 3, sauf
    # 9 h, retirée des deux premiers jours (1 mesure : rapport du site)
    df = pics("SITE001", lambda heure: 2.0 if heure == 8 else 1.2, jours=3)
    df = df[~((df["heure"].dt.hour == 9) & (df["heure"].dt.day < 3))]
    ratios = ratios_pic(df)
    assert ratios[("SITE001", 8)] == 2.0
    assert ratios[("SITE001", 10)] == pytest.approx(1.2)
    # Médiane du site : 1.2 (3 heures à 2 sur 70)
    assert ratios[("SITE001", 9)] == pytest.approx(1.2)
    assert len(ratios) == 24


def test_ratio_absent_sans_assez_d_heures_mesurees():
    df = pd.concat(
        [
            pics_constants("SITE001", 1.5),
            pics_constants("SITE002", 1.5).head(HEURES_MIN_RATIO_SITE - 1),
        ]
    )
    sites = set(ratios_pic(df).index.get_level_values("id_site"))
    assert sites == {"SITE001"}


def test_ratio_jamais_sous_1():
    ratios = ratios_pic(pics_constants("SITE001", 0.8))
    assert (ratios == 1.0).all()


def test_ratio_sans_aucune_mesure():
    vide = pd.DataFrame(
        {
            "id_site": pd.Series(dtype=str),
            "heure": pd.Series(dtype="datetime64[ns, UTC]"),
            "pic_kw": pd.Series(dtype=float),
            "moyenne_kw": pd.Series(dtype=float),
        }
    )
    assert ratios_pic(vide).empty


def test_pic_prevu_avec_fourchette(historique, debut, modeles, caplog):
    p = prevoir(historique, modeles[24], debut, 24)
    ratios = ratios_pic(pics_constants("SITE001", 1.5))
    # Seuil de SITE001 au milieu de ses pics prévus : une partie des heures le dépasse
    pics_001 = 1.5 * p.loc[p["id_site"] == "SITE001", "consommation_prevue_kwh"]
    seuils = pd.Series({"SITE001": float(pics_001.median()), "SITE002": 0.0})
    with caplog.at_level(logging.WARNING):
        a = ajouter_pics(p, ratios, seuils)

    site001 = a[a["id_site"] == "SITE001"]
    assert site001["pic_prevu_kw"].to_numpy() == pytest.approx(
        (site001["consommation_prevue_kwh"] * 1.5).round(2).to_numpy()
    )
    # Le pic ne descend pas sous la consommation, et la fourchette est cohérente
    assert (site001["pic_prevu_kw"] >= site001["consommation_prevue_kwh"]).all()
    assert (site001["pic_bas_kw"] <= site001["pic_prevu_kw"]).all()
    assert (site001["pic_prevu_kw"] <= site001["pic_haut_kw"]).all()
    # pic_prevu vrai si et seulement si le pic atteint le seuil du site
    attendu = site001["pic_prevu_kw"] >= seuils["SITE001"]
    assert (site001["pic_prevu"] == attendu).all()
    assert site001["pic_prevu"].any() and not site001["pic_prevu"].all()

    # SITE002 n'a pas d'historique de pics : pas de pic prévu, même sous un seuil nul
    site002 = a[a["id_site"] == "SITE002"]
    assert site002[["pic_prevu_kw", "pic_bas_kw", "pic_haut_kw"]].isna().all().all()
    assert not site002["pic_prevu"].any()
    assert any(
        "pic de l'heure non prévu" in r.getMessage() and "SITE002" in r.getMessage()
        for r in caplog.records
    )


def test_pic_prevu_sans_fourchette(jeu, historique, debut):
    p = prevoir(historique, production(jeu, 24, "ridge"), debut, 24)
    a = ajouter_pics(
        p, ratios_pic(pics_constants("SITE001", 1.5)), pd.Series({"SITE001": 1e9})
    )
    site001 = a[a["id_site"] == "SITE001"]
    assert site001["pic_prevu_kw"].notna().all()
    assert site001[["pic_bas_kw", "pic_haut_kw"]].isna().all().all()
    assert not site001["pic_prevu"].any()


def test_ecrire_le_pic_prevu(historique, debut, modeles):
    p = prevoir(historique, modeles[24], debut, 24)
    a = ajouter_pics(
        p, ratios_pic(pics_constants("SITE001", 2.0)), pd.Series({"SITE001": 0.0})
    )
    conn = FakeConnection()
    ecrire(conn, a)
    ligne = next(l for l in conn.parametres if l["id_site"] == "SITE001")
    # Arrondi à 2 décimales (NUMERIC(10, 2))
    assert ligne["pic_prevu_kw"] == pytest.approx(
        2 * ligne["consommation_prevue_kwh"], abs=0.005
    )
    assert ligne["pic_bas_kw"] <= ligne["pic_prevu_kw"] <= ligne["pic_haut_kw"]
    assert ligne["pic_prevu"] is True


def test_lire_pics_et_seuils_convertit_les_lignes_de_postgresql(debut):
    paris = timezone(timedelta(hours=1))
    heure = (debut - pd.Timedelta(hours=1)).to_pydatetime().astimezone(paris)

    class Connexion:
        def execute(self, sql, parametres=None):
            self.sql = str(sql)
            self.parametres = parametres
            if "consommation_horaire" in self.sql:
                return FakeResultat(
                    [("SITE001", heure, Decimal("150.00"), Decimal("100.00"))]
                )
            return FakeResultat([("SITE001", Decimal("180.00"), Decimal("200.00"))])

    conn = Connexion()
    df = prevision.lire_pics(conn, debut)
    # Pic soutenu lu dans silver (valeurs mesurées), heures terminées et bien mesurées
    assert "silver.silver_readings" in conn.sql
    assert "consumption_kw_raw" in conn.sql
    assert "heure_complete" in conn.sql
    assert "nb_mesures - c.nb_imputees" in conn.sql
    assert conn.parametres["debut"] == debut
    assert conn.parametres["minutes_min"] == 48
    assert conn.parametres["ecart_max"] == prevision.ECART_MAX_PIC_SOUTENU
    # Triplet dans une seule heure : pic et moyenne portent sur les mêmes minutes
    assert "date_trunc('hour', horodatage_2, 'UTC')" in conn.sql
    assert str(df["heure"].dt.tz) == "UTC"
    assert df.loc[0, "pic_kw"] == 150.0
    assert df.loc[0, "moyenne_kw"] == 100.0

    sites = prevision.lire_sites(conn)
    assert "seuil_alerte_pct" in conn.sql
    assert sites.loc["SITE001", "seuil_kw"] == 180.0
    assert sites.loc["SITE001", "capacite_kw"] == 200.0


def test_ecart_du_pic_soutenu_identique_a_la_detection_de_l_etl():
    """L'ETL coupe la série quand l'écart entre deux minutes dépasse l'intervalle de
    db/17_gold_alertes.sql (« > INTERVAL '5 minutes' ») ; lire_pics garde une paire
    quand l'écart vaut au plus ECART_MAX_PIC_SOUTENU : les deux doivent être égaux."""
    sql = (Path(__file__).parents[2] / "db" / "17_gold_alertes.sql").read_text(
        encoding="utf-8"
    )
    coupures = re.findall(
        r"OVER \([^)]*\)\s*> INTERVAL '(\d+) minutes' AS coupure", sql
    )
    assert coupures, "règle de coupure introuvable dans db/17_gold_alertes.sql"
    assert {pd.Timedelta(minutes=int(m)) for m in coupures} == {
        prevision.ECART_MAX_PIC_SOUTENU
    }
