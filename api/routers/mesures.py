"""Mesures et consommation des sites, lues dans le schéma gold."""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import AwareDatetime, BaseModel, BeforeValidator
from sqlalchemy import text
from sqlalchemy.orm import Session

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
) -> list[DerniereMesure]:
    requete = text(
        """
                SELECT m.id_site, s.nom, s.type, s.capacite_kw,
               m.horodatage, m.consommation_kw, m.data_quality
        FROM gold.derniere_mesure AS m
        JOIN app.site AS s ON s.id_site = m.id_site
        ORDER BY m.id_site
        """
    )
    lignes = session.execute(requete).mappings().all()
    return [DerniereMesure(**ligne) for ligne in lignes]


class ConsommationHoraire(BaseModel):
    heure: datetime
    consommation_kwh: float | None
    cout_eur: float | None


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
    id_site: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,20}$")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    debut: DateIso | None = None,
    fin: DateIso | None = None,
) -> list[ConsommationHoraire]:
    debut, fin = calculer_periode(debut, fin)

    requete = text(
        """
        SELECT heure, consommation_kwh
        FROM gold.consommation_horaire
        WHERE id_site = :id_site AND heure >= :debut AND heure < :fin
        ORDER BY heure
        """
    )
    parametres = {"id_site": id_site, "debut": debut, "fin": fin}
    lignes = session.execute(requete, parametres).mappings().all()

    return [
        ConsommationHoraire(
            heure=ligne["heure"],
            consommation_kwh=ligne["consommation_kwh"],
            cout_eur=calculer_cout(ligne["consommation_kwh"], settings.prix_kwh_eur),
        )
        for ligne in lignes
    ]
