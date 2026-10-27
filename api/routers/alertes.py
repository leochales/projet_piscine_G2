"""Alertes des sites, lues dans app.alerte_etat (gold.alerte et prises en compte)."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import (
    Perimetre,
    PerimetreCourant,
    Utilisateur,
    utilisateur_courant,
    verifier_action_sur_site,
)
from api.routers.parametres import FiltreSite, IdNumerique
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


# Alertes des sites actifs que l'utilisateur voit (PerimetreCourant)
ALERTES_DU_PERIMETRE = """
    SELECT a.id_alerte, a.id_site, s.nom AS nom_site, a.source, a.type,
           a.severite, a.message, a.debut, a.fin, a.valeur, a.seuil,
           a.prise_en_compte, a.prise_par, a.prise_le
    FROM app.alerte_etat AS a
    JOIN app.site AS s ON s.id_site = a.id_site
    WHERE s.statut = 'active'
      AND (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
      AND (CAST(:id_utilisateur_sites AS UUID) IS NULL OR EXISTS (
          SELECT 1 FROM app.utilisateur_site AS us
          WHERE us.id_utilisateur = :id_utilisateur_sites
            AND us.id_site = s.id_site
      ))
"""

REPONSES_PRISE_EN_COMPTE: dict[int | str, dict[str, Any]] = {
    404: {"description": "Alerte inconnue, ou d'un site que l'utilisateur ne voit pas"},
    409: {"description": "Alerte déjà prise en compte, ou terminée"},
}


@router.get(
    "", summary="Alertes des sites actifs : en cours par gravité, puis terminées"
)
def lister_alertes(
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
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
        ALERTES_DU_PERIMETRE
        + """
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
        **perimetre.parametres,
        "en_cours": en_cours,
        "id_site": id_site,
        "limite": limite,
    }
    lignes = session.execute(requete, parametres).mappings().all()
    return [Alerte(**ligne) for ligne in lignes]


def lire_alerte(
    session: Session, id_alerte: int, perimetre: Perimetre
) -> Alerte | None:
    requete = text(ALERTES_DU_PERIMETRE + " AND a.id_alerte = :id_alerte")
    parametres = {**perimetre.parametres, "id_alerte": id_alerte}
    ligne = session.execute(requete, parametres).mappings().first()
    return Alerte(**ligne) if ligne is not None else None


@router.post(
    "/{id_alerte}/prise-en-compte",
    summary="Prendre une alerte en compte (US7)",
    responses=REPONSES_PRISE_EN_COMPTE,
)
def prendre_en_compte(
    id_alerte: IdNumerique,
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
) -> Alerte:
    """Une alerte en cours n'est prise en compte qu'une fois : la deuxième fois, 409.

    GESTION-CLIENT agit sur tous les sites de son client, GESTION-SITE sur ses sites
    attribués ; les autres rôles reçoivent 403. Renvoie l'alerte à jour.
    """
    alerte = lire_alerte(session, id_alerte, perimetre)
    if alerte is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerte inconnue")
    verifier_action_sur_site(session, utilisateur, alerte.id_site)
    if alerte.fin is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alerte terminée")
    if alerte.prise_en_compte:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alerte déjà prise en compte")

    # Deux clics simultanés : la contrainte UNIQUE de la table départage
    ajout = session.execute(
        text(
            "INSERT INTO app.prise_en_compte_alerte (id_alerte, id_utilisateur) "
            "VALUES (:id_alerte, :id_utilisateur) "
            "ON CONFLICT (id_alerte) DO NOTHING RETURNING id_prise_en_compte"
        ),
        {"id_alerte": id_alerte, "id_utilisateur": utilisateur.id},
    ).first()
    if ajout is None:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Alerte déjà prise en compte")
    session.commit()

    a_jour = lire_alerte(session, id_alerte, perimetre)
    if a_jour is None:  # site désactivé entre-temps
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerte inconnue")
    return a_jour
