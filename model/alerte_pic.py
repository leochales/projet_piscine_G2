"""Alerte de pic prévu (SMARTOPS-103) : ``gold.alerte``, source ``modele``, type
``predicted_peak``.

Appelé par ``model.prevision.generer`` après l'écriture des prévisions, dans la même
transaction, avec les prévisions qui viennent d'être écrites. Seules les
``HORIZON_ALERTE`` premières heures comptent : celles du modèle 24 h, le plus précis.
Plus loin, une prévision qui frôle le seuil changerait d'un passage à l'autre, et
l'alerte s'ouvrirait et se fermerait sans cesse. Pour chaque site dont le pic de
l'heure a été prévu (``pic_prevu_kw`` connu) sur ces heures :

  - si au moins une heure atteint le seuil du site (``pic_prevu``, même seuil que la
    détection des pics mesurés de l'ETL), le site a une alerte en cours :
    ``debut`` = première heure au-dessus du seuil, ``valeur`` = plus fort pic prévu
    parmi ces heures, ``valeur_le`` = son heure, ``seuil`` = seuil du site en kW.
    Sévérité ``high``, ``critical`` dès 110 % de la capacité, comme l'ETL ;
  - sinon, son alerte en cours est terminée.

Une seule alerte du modèle en cours par site (index ``uq_alerte_modele_en_cours``,
``db/19_alerte_modele.sql``) : un passage suivant met à jour l'alerte en cours (valeur,
heure du maximum, seuil, sévérité) au lieu d'en créer une autre. Tant que son début
est à venir, il suit la prévision (pic avancé ou retardé) ; une fois atteint, il ne
change plus.

Une alerte terminée a pour fin le moment présent. Un pic annulé avant son heure (plus
prévu) n'a pas eu lieu : son début est ramené au même moment, pour que la fin ne soit
pas dans le futur ; ``valeur_le`` garde l'heure du pic qui était prévu.

Un site sans pic prévu (pas assez d'historique, site écarté de la prévision ou
désactivé) n'est pas évalué : son alerte est gardée tant que l'heure de son pic
(``valeur_le``) n'est pas passée, puis terminée (``terminer``), comme quand aucun
modèle n'est en production.

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
# Heures prévues qui comptent pour l'alerte, à partir de la première
HORIZON_ALERTE = pd.Timedelta(hours=24)
COLONNES = ["id_site", "debut", "valeur", "valeur_le", "seuil", "severite"]


def pics_prevus(
    previsions: pd.DataFrame, sites: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    """Alerte attendue de chaque site qui a au moins une heure au-dessus de son seuil
    dans les ``HORIZON_ALERTE`` premières heures (``COLONNES``), et liste des sites
    évalués : ceux dont le pic a été prévu sur ces heures. ``sites`` : ``seuil_kw`` et
    ``capacite_kw``, indexés par ``id_site``."""
    fin_horizon = previsions["heure_prevue"].min() + HORIZON_ALERTE
    proches = previsions[previsions["heure_prevue"] < fin_horizon]
    evalues = proches[proches["pic_prevu_kw"].notna()]
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
    """Ouvre ou met à jour l'alerte en cours des sites dont un pic est prévu, puis
    termine celles des sites évalués qui n'en ont plus et celles dont le pic est passé
    (``terminer``). Renvoie le nombre d'alertes en cours écrites et le nombre d'alertes
    terminées."""
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
                    -- Début à venir : il suit la prévision ; atteint : il reste
                    debut = CASE
                        WHEN gold.alerte.debut > now() THEN excluded.debut
                        ELSE gold.alerte.debut
                    END
                """
            ),
            pics.astype(object).where(pics.notna(), None).to_dict("records"),
        )
    sans_pic = sorted(set(sites_evalues) - set(pics["id_site"]))
    terminees = terminer(conn, sans_pic)
    logger.info(
        "pics prévus : %d alertes en cours (%s), %d terminées",
        len(pics),
        ", ".join(pics["id_site"]) or "aucune",
        terminees,
    )
    return len(pics), terminees


def terminer(conn: Connection, sans_pic: list[str]) -> int:
    """Termine les alertes en cours du modèle des sites ``sans_pic`` (évalués, plus
    aucune heure au-dessus du seuil), et celles dont l'heure du pic (``valeur_le``) est
    passée : site qui n'est plus évalué, ou plus de modèle en production. Fin = le
    moment présent ; un début encore à venir (pic annulé avant son heure) y est ramené,
    la base exigeant fin >= debut. Renvoie le nombre d'alertes terminées."""
    return len(
        conn.execute(
            text(
                """
                UPDATE gold.alerte
                SET fin = now(), debut = least(debut, now())
                WHERE source = 'modele'
                  AND type = 'predicted_peak'
                  AND fin IS null
                  AND (
                      id_site = ANY(:sites)
                      OR coalesce(valeur_le, debut) + interval '1 hour' <= now()
                  )
                RETURNING id_alerte
                """
            ),
            {"sites": sans_pic},
        ).all()
    )
