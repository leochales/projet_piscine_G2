"""Alerte de pic prévu (SMARTOPS-103) : ``gold.alerte``, source ``modele``, type
``predicted_peak``.

Appelé par ``model.prevision.generer`` après l'écriture des prévisions, dans la même
transaction, avec les prévisions qui viennent d'être écrites. Pour chaque site dont le
pic de l'heure a été prévu (``pic_prevu_kw`` connu) :

  - si au moins une heure prévue atteint le seuil du site (``pic_prevu``, même seuil
    que la détection des pics mesurés de l'ETL), le site a une alerte en cours :
    ``debut`` = première heure au-dessus du seuil, ``valeur`` = plus fort pic prévu
    parmi ces heures, ``valeur_le`` = son heure, ``seuil`` = seuil du site en kW.
    Sévérité ``high``, ``critical`` dès 110 % de la capacité, comme l'ETL ;
  - sinon, son alerte en cours est terminée.

Une seule alerte du modèle en cours par site (index ``uq_alerte_modele_en_cours``,
``db/19_alerte_modele.sql``) : un passage suivant met à jour l'alerte en cours (valeur,
heure du maximum, seuil, sévérité) au lieu d'en créer une autre. Son début reste le
premier : il n'avance que si le pic est désormais prévu plus tôt.

Un site sans pic prévu (pas assez d'historique, site écarté de la prévision) n'est pas
évalué : son alerte en cours, s'il en a une, n'est ni mise à jour ni terminée.

La version du modèle qui a produit l'alerte se lit dans ``gold.prediction`` : la
prévision de ``valeur_le`` pour ce site porte ``version_modele``.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import Connection, text

logger = logging.getLogger(__name__)

# Sévérité critical dès ce pourcentage de la capacité, comme les pics mesurés de l'ETL
# (db/17_gold_alertes.sql)
CRITIQUE_PCT = 110
COLONNES = ["id_site", "debut", "valeur", "valeur_le", "seuil", "severite"]


def pics_prevus(
    previsions: pd.DataFrame, sites: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    """Alerte attendue de chaque site qui a au moins une heure au-dessus de son seuil
    (``COLONNES``), et liste des sites évalués : ceux dont le pic a été prévu.
    ``sites`` : ``seuil_kw`` et ``capacite_kw``, indexés par ``id_site``."""
    evalues = previsions[previsions["pic_prevu_kw"].notna()]
    sites_evalues = sorted(evalues["id_site"].unique())
    hautes = evalues[evalues["pic_prevu"].astype(bool)]
    if hautes.empty:
        return pd.DataFrame(columns=COLONNES), sites_evalues
    maximum = hautes.loc[hautes.groupby("id_site")["pic_prevu_kw"].idxmax()].set_index(
        "id_site"
    )
    pics = pd.DataFrame(
        {
            "debut": hautes.groupby("id_site")["heure_prevue"].min(),
            "valeur": maximum["pic_prevu_kw"].astype(float),
            "valeur_le": maximum["heure_prevue"],
        }
    )
    pics["seuil"] = sites["seuil_kw"].reindex(pics.index)
    capacite = sites["capacite_kw"].reindex(pics.index)
    pics["severite"] = np.where(
        pics["valeur"] >= capacite * CRITIQUE_PCT / 100, "critical", "high"
    )
    return pics.rename_axis("id_site").reset_index()[COLONNES], sites_evalues


def mettre_a_jour(
    conn: Connection, previsions: pd.DataFrame, sites: pd.DataFrame
) -> tuple[int, int]:
    """Ouvre ou met à jour l'alerte en cours des sites dont un pic est prévu, et
    termine celle des sites évalués qui n'en ont plus. Renvoie le nombre d'alertes en
    cours écrites et le nombre d'alertes terminées."""
    pics, sites_evalues = pics_prevus(previsions, sites)
    if not pics.empty:
        conn.execute(
            text(
                """
                INSERT INTO gold.alerte (
                    id_site, source, type, severite, debut, valeur, valeur_le, seuil
                )
                VALUES (
                    :id_site, 'modele', 'predicted_peak', :severite, :debut,
                    :valeur, :valeur_le, :seuil
                )
                ON CONFLICT (id_site, type)
                WHERE source = 'modele' AND fin IS null
                DO UPDATE SET
                    severite = excluded.severite,
                    valeur = excluded.valeur,
                    valeur_le = excluded.valeur_le,
                    seuil = excluded.seuil,
                    debut = least(gold.alerte.debut, excluded.debut)
                """
            ),
            pics.astype(object).where(pics.notna(), None).to_dict("records"),
        )
    sans_pic = sorted(set(sites_evalues) - set(pics["id_site"]))
    terminees = []
    if sans_pic:
        # Terminée maintenant, ou à son début s'il est encore à venir (pic annoncé
        # puis plus prévu) : la base exige fin >= debut
        terminees = conn.execute(
            text(
                """
                UPDATE gold.alerte
                SET fin = greatest(debut, now())
                WHERE source = 'modele'
                  AND type = 'predicted_peak'
                  AND fin IS null
                  AND id_site = ANY(:sites)
                RETURNING id_alerte
                """
            ),
            {"sites": sans_pic},
        ).all()
    logger.info(
        "pics prévus : %d alertes en cours (%s), %d terminées",
        len(pics),
        ", ".join(pics["id_site"]) or "aucune",
        len(terminees),
    )
    return len(pics), len(terminees)
