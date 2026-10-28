"""Recommandations et économies réalisées, lues dans les vues de app."""

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
from api.routers.mesures import DateIso
from api.routers.parametres import FiltreSite, IdNumerique
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


class Decision(BaseModel):
    statut: Literal["acceptee", "refusee"]


class Economies(BaseModel):
    id_site: str
    nb_recommandations_acceptees: int
    economies_eur: float


# Recommandations des sites actifs que l'utilisateur voit (PerimetreCourant)
RECOMMANDATIONS_DU_PERIMETRE = """
    SELECT r.id_recommandation, r.id_site, s.nom AS nom_site, r.id_alerte,
           r.regle, r.titre, r.description, r.date_creation,
           r.gain_estime_eur, r.periode_gain, r.statut,
           r.decide_par, r.decide_le
    FROM app.recommandation_etat AS r
    JOIN app.site AS s ON s.id_site = r.id_site
    -- Alerte qui a déclenché la recommandation, pour le filtre alerte_en_cours
    LEFT JOIN gold.alerte AS a ON a.id_alerte = r.id_alerte
    WHERE s.statut = 'active'
      AND (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
      AND (CAST(:id_utilisateur_sites AS UUID) IS NULL OR EXISTS (
          SELECT 1 FROM app.utilisateur_site AS us
          WHERE us.id_utilisateur = :id_utilisateur_sites
            AND us.id_site = s.id_site
      ))
"""

REPONSES_DECISION: dict[int | str, dict[str, Any]] = {
    # Réponse de FastAPI quand le corps ne peut pas être lu (octets quelconques, comme
    # ceux de Schemathesis) ; un JSON mal formé donne 422
    400: {"description": "Corps de la requête illisible"},
    404: {
        "description": "Recommandation inconnue, ou d'un site que l'utilisateur ne voit pas"
    },
    409: {"description": "Recommandation déjà acceptée ou refusée"},
}


@router.get("", summary="Recommandations des sites actifs, les plus récentes d'abord")
def lister_recommandations(
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
    id_site: FiltreSite = None,
    statut: Statut | None = None,
    alerte_en_cours: Annotated[
        bool | None,
        Query(
            description="true : alerte en cours ou sans alerte ; false : alerte terminée"
        ),
    ] = None,
    decidee_depuis: Annotated[
        DateIso | None, Query(description="Décidées à cette date ou après")
    ] = None,
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Recommandation]:
    # Une recommandation sans alerte compte comme en cours (a.fin vide) : rien
    # ne dit qu'elle n'a plus d'objet
    requete = text(
        RECOMMANDATIONS_DU_PERIMETRE
        + """
          AND (CAST(:id_site AS VARCHAR) IS NULL OR r.id_site = :id_site)
          AND (CAST(:statut AS VARCHAR) IS NULL OR r.statut = :statut)
          AND (CAST(:alerte_en_cours AS BOOLEAN) IS NULL
               OR (a.fin IS NULL) = :alerte_en_cours)
          AND (CAST(:decidee_depuis AS TIMESTAMPTZ) IS NULL
               OR r.decide_le >= :decidee_depuis)
        ORDER BY r.date_creation DESC, r.id_recommandation DESC
        LIMIT :limite
        """
    )
    parametres = {
        **perimetre.parametres,
        "id_site": id_site,
        "statut": statut,
        "alerte_en_cours": alerte_en_cours,
        "decidee_depuis": decidee_depuis,
        "limite": limite,
    }
    lignes = session.execute(requete, parametres).mappings().all()
    return [Recommandation(**ligne) for ligne in lignes]


@router.get("/economies", summary="Économies réalisées par site")
def lister_economies(
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
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
          AND (CAST(:id_utilisateur_sites AS UUID) IS NULL OR EXISTS (
              SELECT 1 FROM app.utilisateur_site AS us
              WHERE us.id_utilisateur = :id_utilisateur_sites
                AND us.id_site = s.id_site
          ))
        ORDER BY s.id_site
        """
    )
    lignes = session.execute(requete, perimetre.parametres).mappings().all()
    return [Economies(**ligne) for ligne in lignes]


def lire_recommandation(
    session: Session, id_recommandation: int, perimetre: Perimetre
) -> Recommandation | None:
    requete = text(
        RECOMMANDATIONS_DU_PERIMETRE + " AND r.id_recommandation = :id_recommandation"
    )
    parametres = {**perimetre.parametres, "id_recommandation": id_recommandation}
    ligne = session.execute(requete, parametres).mappings().first()
    return Recommandation(**ligne) if ligne is not None else None


@router.post(
    "/{id_recommandation}/decision",
    summary="Accepter ou refuser une recommandation (US7)",
    responses=REPONSES_DECISION,
)
def decider(
    id_recommandation: IdNumerique,
    decision: Decision,
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
) -> Recommandation:
    """Une recommandation n'est décidée qu'une fois : ensuite, 409 (pas de changement
    d'avis).

    GESTION-CLIENT agit sur tous les sites de son client, GESTION-SITE sur ses sites
    attribués ; les autres rôles reçoivent 403. Renvoie la recommandation à jour.
    """
    recommandation = lire_recommandation(session, id_recommandation, perimetre)
    if recommandation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommandation inconnue")
    verifier_action_sur_site(session, utilisateur, recommandation.id_site)
    if recommandation.statut != "proposee":
        raise HTTPException(status.HTTP_409_CONFLICT, "Recommandation déjà décidée")

    # Deux décisions simultanées : l'index unique (db/16) départage
    ajout = session.execute(
        text(
            "INSERT INTO app.decision_recommandation "
            "(id_recommandation, id_utilisateur, statut) "
            "VALUES (:id_recommandation, :id_utilisateur, :statut) "
            "ON CONFLICT (id_recommandation) DO NOTHING RETURNING id_decision"
        ),
        {
            "id_recommandation": id_recommandation,
            "id_utilisateur": utilisateur.id,
            "statut": decision.statut,
        },
    ).first()
    if ajout is None:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Recommandation déjà décidée")

    # Relue avant le commit : un site désactivé entre-temps donne 404 sans rien
    # enregistrer, et non 404 sur une décision déjà faite
    a_jour = lire_recommandation(session, id_recommandation, perimetre)
    if a_jour is None:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommandation inconnue")
    session.commit()
    return a_jour
