"""Recommandations et économies réalisées, lues dans les vues de app."""

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

router = APIRouter(prefix="/recommandations", tags=["recommandations"])

Statut = Literal["proposee", "acceptee", "refusee"]


class Recommandation(BaseModel):
    id_recommandation: int
    id_site: str
    nom_site: str
    id_alerte: int | None  # alerte qui a déclenché la recommandation
    regle: str
    titre: str
    description: str | None
    date_creation: datetime
    # Gain et période : tous deux null si le gain n'est pas estimé
    gain_estime_eur: float | None
    periode_gain: Literal["unique", "semaine"] | None
    statut: Statut  # dernière décision, « proposee » tant que personne n'a décidé
    decide_par: UUID | None  # identifiant Keycloak
    decide_le: datetime | None


class Economies(BaseModel):
    id_site: str
    nb_recommandations_acceptees: int
    economies_eur: float


@router.get("", summary="Recommandations des sites actifs, les plus récentes d'abord")
def lister_recommandations(
    session: Annotated[Session, Depends(get_session)],
    id_client: ClientCourant,
    id_site: FiltreSite = None,
    statut: Statut | None = None,
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Recommandation]:
    requete = text(
        """
        SELECT r.id_recommandation, r.id_site, s.nom AS nom_site, r.id_alerte,
               r.regle, r.titre, r.description, r.date_creation,
               r.gain_estime_eur, r.periode_gain, r.statut,
               r.decide_par, r.decide_le
        FROM app.recommandation_etat AS r
        JOIN app.site AS s ON s.id_site = r.id_site
        WHERE s.statut = 'active'
          AND (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
          AND (CAST(:id_site AS VARCHAR) IS NULL OR r.id_site = :id_site)
          AND (CAST(:statut AS VARCHAR) IS NULL OR r.statut = :statut)
        ORDER BY r.date_creation DESC, r.id_recommandation DESC
        LIMIT :limite
        """
    )
    parametres = {
        "id_client": id_client,
        "id_site": id_site,
        "statut": statut,
        "limite": limite,
    }
    lignes = session.execute(requete, parametres).mappings().all()
    return [Recommandation(**ligne) for ligne in lignes]


@router.get("/economies", summary="Économies réalisées par site")
def lister_economies(
    session: Annotated[Session, Depends(get_session)],
    id_client: ClientCourant,
) -> list[Economies]:
    """Somme des gains estimés des recommandations acceptées (app.economies_realisees).

    Un site actif sans recommandation acceptée figure avec 0 €.
    """
    requete = text(
        """
        SELECT s.id_site,
               coalesce(e.nb_recommandations_acceptees, 0)
                   AS nb_recommandations_acceptees,
               coalesce(e.economies_eur, 0) AS economies_eur
        FROM app.site AS s
        LEFT JOIN app.economies_realisees AS e ON e.id_site = s.id_site
        WHERE s.statut = 'active'
          AND (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
        ORDER BY s.id_site
        """
    )
    lignes = session.execute(requete, {"id_client": id_client}).mappings().all()
    return [Economies(**ligne) for ligne in lignes]
