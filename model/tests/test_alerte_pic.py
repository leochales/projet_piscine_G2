import logging

import numpy as np
import pandas as pd
import pytest

from model import alerte_pic
from model.alerte_pic import mettre_a_jour, pics_prevus

DEBUT = pd.Timestamp("2026-10-29 10:00", tz="UTC")
# Seuil de 450 kW pour une capacité de 500 kW (bureau, 90 %) : critical dès 550 kW
SITES = pd.DataFrame(
    {
        "seuil_kw": [450.0, 900.0, 180.0],
        "capacite_kw": [500.0, 1000.0, 200.0],
    },
    index=pd.Index(["SITE001", "SITE002", "SITE003"], name="id_site"),
)


def previsions(id_site: str, pics: list[float | None]) -> pd.DataFrame:
    """Prévisions d'un site, une heure par pic prévu, telles que ``ajouter_pics``
    les rend : ``pic_prevu`` vrai quand le pic atteint le seuil du site."""
    pic = np.array([np.nan if p is None else p for p in pics], dtype=float)
    return pd.DataFrame(
        {
            "id_site": id_site,
            "heure_prevue": pd.date_range(DEBUT, periods=len(pics), freq="h"),
            "pic_prevu_kw": pic,
            "pic_prevu": pic >= SITES.loc[id_site, "seuil_kw"],
        }
    )


class Connexion:
    def __init__(self, terminees=0):
        self.requetes = []
        self.terminees = terminees

    def execute(self, sql, parametres=None):
        self.requetes.append((" ".join(str(sql).split()), parametres))
        lignes = [(i,) for i in range(self.terminees)]

        class Resultat:
            def all(self):
                return lignes

        return Resultat()


def test_alerte_debut_valeur_et_seuil():
    # Au-dessus du seuil de 11 h à 13 h, maximum à 12 h
    pics, evalues = pics_prevus(previsions("SITE001", [400, 460, 520, 455, 300]), SITES)
    assert evalues == ["SITE001"]
    alerte = pics.iloc[0]
    assert alerte["id_site"] == "SITE001"
    assert alerte["debut"] == DEBUT + pd.Timedelta(hours=1)
    assert alerte["valeur"] == 520
    assert alerte["valeur_le"] == DEBUT + pd.Timedelta(hours=2)
    assert alerte["seuil"] == 450
    assert alerte["severite"] == "high"


@pytest.mark.parametrize(
    ("maximum", "severite"), [(549.99, "high"), (550, "critical"), (600, "critical")]
)
def test_critique_des_110_pct_de_la_capacite(maximum, severite):
    pics, _ = pics_prevus(previsions("SITE001", [460, maximum]), SITES)
    assert pics.iloc[0]["severite"] == severite


def test_site_sans_heure_au_dessus_du_seuil_evalue_sans_alerte():
    pics, evalues = pics_prevus(previsions("SITE001", [400, 449.99]), SITES)
    assert pics.empty
    assert evalues == ["SITE001"]


def test_site_sans_pic_prevu_pas_evalue():
    pics, evalues = pics_prevus(previsions("SITE001", [None, None]), SITES)
    assert pics.empty
    assert evalues == []


def test_mettre_a_jour_ouvre_et_termine(caplog):
    p = pd.concat(
        [
            previsions("SITE001", [460, 470]),  # pic prévu : alerte en cours
            previsions("SITE002", [500, 600]),  # plus de pic : alerte terminée
            previsions("SITE003", [None, None]),  # pas évalué : on n'y touche pas
        ],
        ignore_index=True,
    )
    conn = Connexion(terminees=1)
    with caplog.at_level(logging.INFO):
        assert mettre_a_jour(conn, p, SITES) == (1, 1)

    (upsert, lignes), (fermeture, parametres) = conn.requetes
    assert "INSERT INTO gold.alerte" in upsert
    assert "'modele', 'predicted_peak'" in upsert
    # Une seule alerte en cours par site : mise à jour, début gardé s'il est plus tôt
    assert (
        "ON CONFLICT (id_site, type) WHERE source = 'modele' AND fin IS null" in upsert
    )
    assert "least(gold.alerte.debut, excluded.debut)" in upsert
    assert [l["id_site"] for l in lignes] == ["SITE001"]
    assert lignes[0]["valeur"] == 470

    assert "SET fin = greatest(debut, now())" in fermeture
    assert "source = 'modele'" in fermeture
    assert parametres == {"sites": ["SITE002"]}
    assert any("1 alertes en cours" in r.getMessage() for r in caplog.records)


def test_mettre_a_jour_sans_aucun_site_evalue_ne_touche_a_rien():
    conn = Connexion()
    assert mettre_a_jour(conn, previsions("SITE001", [None]), SITES) == (0, 0)
    assert conn.requetes == []


def test_seule_la_fermeture_quand_aucun_pic():
    conn = Connexion(terminees=0)
    assert mettre_a_jour(conn, previsions("SITE001", [100]), SITES) == (0, 0)
    assert len(conn.requetes) == 1
    assert "UPDATE gold.alerte" in conn.requetes[0][0]


def test_valeurs_converties_pour_postgresql():
    """Pas de type numpy ni de NaN dans les paramètres envoyés à la base."""
    conn = Connexion()
    mettre_a_jour(conn, previsions("SITE001", [460]), SITES)
    ligne = conn.requetes[0][1][0]
    assert isinstance(ligne["valeur"], float)
    assert isinstance(ligne["severite"], str)
    assert ligne["seuil"] == 450.0
    assert alerte_pic.CRITIQUE_PCT == 110
