"""Mesures et consommation des sites, lues dans le schéma gold."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, BeforeValidator
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


DateIso = Annotated[datetime, BeforeValidator(lire_date_iso)]


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


class ConsommationHoraire(BaseModel):
    heure: datetime
    consommation_kwh: float | None
    cout_eur: float | None


def calculer_cout(consommation_kwh: Decimal | None, prix_kwh: float) -> float | None:
    if consommation_kwh is None:
        return None
    return round(float(consommation_kwh) * prix_kwh, 2)


@router.get("/{id_site}/consommation", summary="Consommation horaire d'un site")
def lister_consommation_horaire(
    id_site: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,20}$")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    debut: DateIso | None = None,
    fin: DateIso | None = None,
) -> list[ConsommationHoraire]:
    fin = fin or datetime.now(UTC)
    debut = debut or fin - timedelta(hours=24)

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
