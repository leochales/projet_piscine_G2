"""Prévisions de consommation des sites, lues dans gold.prediction."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import PerimetreCourant
from api.routers.parametres import IdSite
from common.db import get_session

router = APIRouter(prefix="/sites", tags=["prédictions"])

Horizon = Literal["24h", "7j"]
DUREES: dict[Horizon, timedelta] = {"24h": timedelta(hours=24), "7j": timedelta(days=7)}

UNE_HEURE = timedelta(hours=1)


class Prediction(BaseModel):
    heure: datetime
    consommation_kwh: float
    # Fourchette : null si le modèle n'en donne pas (prévision de référence)
    consommation_basse_kwh: float | None
    consommation_haute_kwh: float | None
    pic_prevu: bool
    # Maximum de l'heure et sa fourchette : null si le modèle ne les calcule pas
    pic_prevu_kw: float | None
    pic_bas_kw: float | None
    pic_haut_kw: float | None
    calculee_le: datetime
    version_modele: str


def calculer_fenetre(
    horizon: Horizon, maintenant: datetime | None = None
) -> tuple[datetime, datetime]:
    """Heures à prévoir : de l'heure pleine qui suit jusqu'à l'horizon (fin exclue).

    L'heure en cours est déjà entamée : « 24h » renvoie les 24 heures à venir.
    """
    maintenant = maintenant or datetime.now(UTC)
    debut = maintenant.replace(minute=0, second=0, microsecond=0) + UNE_HEURE
    return debut, debut + DUREES[horizon]


@router.get("/{id_site}/predictions", summary="Prévisions de consommation d'un site")
def lister_predictions(
    id_site: IdSite,
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
    horizon: Horizon = "24h",
) -> list[Prediction]:
    debut, fin = calculer_fenetre(horizon)

    # Le modèle ajoute des lignes à chaque exécution (historique conservé) :
    # pour chaque heure, on garde la prévision la plus récente.
    requete = text(
        """
        SELECT DISTINCT ON (heure_prevue)
               heure_prevue AS heure,
               consommation_prevue_kwh AS consommation_kwh,
               consommation_basse_kwh, consommation_haute_kwh,
               pic_prevu, pic_prevu_kw, pic_bas_kw, pic_haut_kw,
               calculee_le, version_modele
        FROM gold.prediction
        WHERE id_site = :id_site AND heure_prevue >= :debut AND heure_prevue < :fin
          -- Site d'un autre client : aucune ligne, comme un site inconnu
          AND EXISTS (
              SELECT 1 FROM app.site AS s
              WHERE s.id_site = :id_site
                AND (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
                AND (CAST(:id_utilisateur_sites AS UUID) IS NULL OR EXISTS (
                    SELECT 1 FROM app.utilisateur_site AS us
                    WHERE us.id_utilisateur = :id_utilisateur_sites
                      AND us.id_site = s.id_site
                ))
          )
        ORDER BY heure_prevue, calculee_le DESC
        """
    )
    parametres = {
        "id_site": id_site,
        "debut": debut,
        "fin": fin,
        **perimetre.parametres,
    }
    lignes = session.execute(requete, parametres).mappings().all()
    return [Prediction(**ligne) for ligne in lignes]
