"""Alertes des sites, lues dans app.alerte_etat (gold.alerte et prises en compte)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import ClientCourant
from api.routers.parametres import FiltreSite
from common.db import get_session

router = APIRouter(prefix="/alertes", tags=["alertes"])


class Alerte(BaseModel):
    id_alerte: int
    id_site: str
    nom_site: str
    source: Literal["api_mock", "etl", "modele"]
    type: Literal["spike", "threshold", "anomaly", "outage", "sensor", "predicted_peak"]
    severite: Literal["low", "medium", "high", "critical"]
    message: str | None
    debut: datetime
    fin: datetime | None  # null : alerte en cours
    valeur: float | None
    seuil: float | None
    prise_en_compte: bool
    prise_par: UUID | None  # identifiant Keycloak
    prise_le: datetime | None


@router.get(
    "", summary="Alertes des sites actifs : en cours par gravité, puis terminées"
)
def lister_alertes(
    session: Annotated[Session, Depends(get_session)],
    id_client: ClientCourant,
    en_cours: Annotated[
        bool, Query(description="false : inclut les alertes terminées")
    ] = True,
    id_site: FiltreSite = None,
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Alerte]:
    # Alertes en cours d'abord, les plus graves en tête. Les alertes terminées
    # suivent par date : une vieille alerte critique ne doit pas cacher les
    # alertes récentes quand la limite est atteinte.
    requete = text(
        """
        SELECT a.id_alerte, a.id_site, s.nom AS nom_site, a.source, a.type,
               a.severite, a.message, a.debut, a.fin, a.valeur, a.seuil,
               a.prise_en_compte, a.prise_par, a.prise_le
        FROM app.alerte_etat AS a
        JOIN app.site AS s ON s.id_site = a.id_site
        WHERE s.statut = 'active'
          AND (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
          AND (NOT :en_cours OR a.fin IS NULL)
          AND (CAST(:id_site AS VARCHAR) IS NULL OR a.id_site = :id_site)
        ORDER BY a.fin IS NULL DESC,
                 CASE WHEN a.fin IS NULL THEN
                     CASE a.severite
                         WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                         WHEN 'medium' THEN 3 ELSE 4
                     END
                 END,
                 a.debut DESC, a.id_alerte DESC
        LIMIT :limite
        """
    )
    parametres = {
        "id_client": id_client,
        "en_cours": en_cours,
        "id_site": id_site,
        "limite": limite,
    }
    lignes = session.execute(requete, parametres).mappings().all()
    return [Alerte(**ligne) for ligne in lignes]
