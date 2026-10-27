"""Utilisateur connecté, vu par l'API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import ROLES_APPLICATION, Utilisateur, utilisateur_courant
from common.db import get_session

router = APIRouter(prefix="/moi", tags=["utilisateurs"])


class Moi(BaseModel):
    id: UUID  # identifiant Keycloak (sub du jeton)
    id_client: int | None  # null : administrateur EnerVision, sans client
    roles: list[str]  # rôles de l'application seulement (pas ceux propres à Keycloak)
    # Sites attribués (app.utilisateur_site) : ceux d'un rôle *-SITE. Vide pour un rôle
    # *-CLIENT, qui voit et gère tous les sites de son client
    sites: list[str]


@router.get("", summary="Utilisateur connecté : identifiant, client et rôles")
def lire_moi(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[Session, Depends(get_session)],
) -> Moi:
    """Appelée par le front juste après la connexion.

    Vérifie que l'API accepte le jeton (sinon 401) et que le compte est enregistré
    dans app.utilisateur (sinon 403, compte non rattaché). Ouverte à tous les rôles :
    elle ne renvoie que l'utilisateur lui-même.
    """
    requete = text(
        "SELECT id_site FROM app.utilisateur_site WHERE id_utilisateur = :id "
        "ORDER BY id_site"
    )
    sites = session.execute(requete, {"id": utilisateur.id}).scalars().all()
    return Moi(
        id=utilisateur.id,
        id_client=utilisateur.id_client,
        roles=sorted(utilisateur.roles & set(ROLES_APPLICATION)),
        sites=list(sites),
    )
