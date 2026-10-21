"""Mesures et consommation des sites, lues dans le schéma gold."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from common.db import get_session

router = APIRouter(prefix="/sites", tags=["mesures"])


class DerniereMesure(BaseModel):
    id_site: str
    nom: str
    horodatage: datetime
    consommation_kw: float | None
    data_quality: str


@router.get("/derniere-mesure", summary="Dernière mesure de chaque site")
def lister_dernieres_mesures(
    session: Annotated[Session, Depends(get_session)],
) -> list[DerniereMesure]:
    requete = text(
        """
        SELECT m.id_site, s.nom, m.horodatage, m.consommation_kw, m.data_quality
        FROM gold.derniere_mesure AS m
        JOIN app.site AS s ON s.id_site = m.id_site
        ORDER BY m.id_site
        """
    )
    lignes = session.execute(requete).mappings().all()
    return [DerniereMesure(**ligne) for ligne in lignes]
