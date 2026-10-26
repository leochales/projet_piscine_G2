"""Utilisateur connecté, vu par l'API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import Utilisateur, utilisateur_courant

router = APIRouter(prefix="/moi", tags=["utilisateurs"])


class Moi(BaseModel):
    id: UUID  # identifiant Keycloak (sub du jeton)
    id_client: int | None  # null : administrateur EnerVision, sans client
    roles: list[str]


@router.get("", summary="Utilisateur connecté : identifiant, client et rôles")
def lire_moi(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
) -> Moi:
    """Appelée par le front juste après la connexion.

    Vérifie que l'API accepte le jeton (sinon 401) et que le compte est enregistré
    dans app.utilisateur (sinon 403, compte non rattaché). Ouverte à tous les rôles :
    elle ne renvoie que l'utilisateur lui-même.
    """
    return Moi(
        id=utilisateur.id,
        id_client=utilisateur.id_client,
        roles=sorted(utilisateur.roles),
    )
