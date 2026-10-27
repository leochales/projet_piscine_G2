"""Mesures et consommation des sites, lues dans le schéma gold."""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, BeforeValidator
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import PerimetreCourant
from api.routers.parametres import IdSite
from common.config import Settings, get_settings
from common.db import get_session

router = APIRouter(prefix="/sites", tags=["mesures"])


def lire_date_iso(valeur: Any) -> datetime:
    """Refuse les nombres (timestamps Unix) : seul le format ISO 8601 est accepté."""
    if isinstance(valeur, datetime):
        return valeur
    return datetime.fromisoformat(valeur)


DateIso = Annotated[AwareDatetime, BeforeValidator(lire_date_iso)]


class DerniereMesure(BaseModel):
    id_site: str
    nom: str
    type: str
    capacite_kw: float
    horodatage: datetime
    consommation_kw: float | None
    data_quality: Literal["good", "partial", "degraded", "critical"]


@router.get("/derniere-mesure", summary="Dernière mesure de chaque site")
def lister_dernieres_mesures(
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
) -> list[DerniereMesure]:
    requete = text(
        """
        SELECT m.id_site, s.nom, s.type, s.capacite_kw,
               m.horodatage, m.consommation_kw, m.data_quality
        FROM gold.derniere_mesure AS m
        JOIN app.site AS s ON s.id_site = m.id_site
        WHERE (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
          AND (CAST(:id_utilisateur_sites AS UUID) IS NULL OR EXISTS (
              SELECT 1 FROM app.utilisateur_site AS us
              WHERE us.id_utilisateur = :id_utilisateur_sites
                AND us.id_site = s.id_site
          ))
        ORDER BY m.id_site
        """
    )
    lignes = session.execute(requete, perimetre.parametres).mappings().all()
    return [DerniereMesure(**ligne) for ligne in lignes]


Capteur = Literal["consumption", "electrical", "temperature", "humidity", "network"]


class EtatSite(BaseModel):
    id_site: str
    nom: str
    # Dernière mesure transmise par le site (hors perte réseau), null s'il n'a jamais transmis
    derniere_mesure_le: datetime | None
    # Faux si la panne est de notre côté (ETL arrêté, API Mock injoignable)
    collecte_a_jour: bool
    # Null (inconnu) quand la collecte n'est pas à jour : on n'accuse pas le site
    transmet: bool | None
    # Null tant que l'état des capteurs n'a jamais été lu
    etat_capteurs: Literal["ok", "degraded", "critical"] | None
    capteurs_en_panne: list[Capteur]
    retablissement_prevu: datetime | None


@router.get("/etat", summary="Transmission et capteurs de chaque site")
def lister_etats(
    session: Annotated[Session, Depends(get_session)],
    perimetre: PerimetreCourant,
) -> list[EtatSite]:
    requete = text(
        """
        SELECT e.id_site, s.nom, e.derniere_mesure_le, e.collecte_a_jour,
               e.transmet, e.etat_capteurs, e.capteurs_en_panne,
               e.retablissement_prevu
        FROM gold.etat_site AS e
        JOIN app.site AS s ON s.id_site = e.id_site
        WHERE (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
          AND (CAST(:id_utilisateur_sites AS UUID) IS NULL OR EXISTS (
              SELECT 1 FROM app.utilisateur_site AS us
              WHERE us.id_utilisateur = :id_utilisateur_sites
                AND us.id_site = s.id_site
          ))
        ORDER BY e.id_site
        """
    )
    lignes = session.execute(requete, perimetre.parametres).mappings().all()
    return [EtatSite(**ligne) for ligne in lignes]


class ConsommationHoraire(BaseModel):
    heure: datetime
    consommation_kwh: float | None
    cout_eur: float | None
    # Minutes de l'heure reconstituées par imputation en silver (valeurs estimées)
    nb_imputees: int
    # Part des 60 minutes qui ont une consommation, mesurée ou imputée
    taux_couverture: float


CENTIME = Decimal("0.01")


def calculer_cout(consommation_kwh: Decimal | None, prix_kwh: Decimal) -> float | None:
    """Coût en euros, arrondi au centime le plus proche (0,125 donne 0,13)."""
    if consommation_kwh is None:
        return None
    cout = (consommation_kwh * prix_kwh).quantize(CENTIME, rounding=ROUND_HALF_UP)
    return float(cout)


PERIODE_PAR_DEFAUT = timedelta(hours=24)
PERIODE_MAX = timedelta(days=31)


def calculer_periode(
    debut: datetime | None, fin: datetime | None
) -> tuple[datetime, datetime]:
    """Complète et contrôle la période demandée. Lève une erreur 400 si elle est invalide."""
    if fin is None:
        fin = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    if debut is None:
        try:
            debut = fin - PERIODE_PAR_DEFAUT
        except OverflowError:
            raise HTTPException(400, "fin est trop ancienne") from None
    if debut >= fin:
        raise HTTPException(400, "debut doit être avant fin")
    if fin - debut > PERIODE_MAX:
        raise HTTPException(400, "la période est limitée à 31 jours")
    return debut, fin


@router.get(
    "/{id_site}/consommation",
    summary="Consommation horaire d'un site",
    responses={400: {"description": "Période invalide"}},
)
def lister_consommation_horaire(
    id_site: IdSite,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    perimetre: PerimetreCourant,
    debut: DateIso | None = None,
    fin: DateIso | None = None,
) -> list[ConsommationHoraire]:
    debut, fin = calculer_periode(debut, fin)

    requete = text(
        """
        SELECT heure, consommation_kwh, nb_imputees, taux_couverture
        FROM gold.consommation_horaire
        WHERE id_site = :id_site AND heure >= :debut AND heure < :fin
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
        ORDER BY heure
        """
    )
    parametres = {
        "id_site": id_site,
        "debut": debut,
        "fin": fin,
        **perimetre.parametres,
    }
    lignes = session.execute(requete, parametres).mappings().all()

    return [
        ConsommationHoraire(
            heure=ligne["heure"],
            consommation_kwh=ligne["consommation_kwh"],
            cout_eur=calculer_cout(ligne["consommation_kwh"], settings.prix_kwh_eur),
            nb_imputees=ligne["nb_imputees"],
            taux_couverture=ligne["taux_couverture"],
        )
        for ligne in lignes
    ]
