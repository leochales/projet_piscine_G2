"""Contrat des réponses de l'API Mock (OpenAPI v1.1.0), validé avec Pydantic.

À l'extraction, seule la clé d'une mesure (``site_id`` et ``timestamp``) est
contrôlée par ``ReadingKey`` : c'est ce qu'il faut pour l'écrire en bronze.
Le reste du payload est stocké tel quel, même mal formé, pour pouvoir être
analysé ; la validation complète se fait au passage bronze → silver.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _force_utc(ts: datetime) -> datetime:
    # /readings renvoie "…Z" ; /current et /alerts des dates sans fuseau,
    # qui sont en UTC dans les faits
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_force_utc)]


class SiteInfo(BaseModel):
    """GET /api/v1/sites : un site industriel simulé."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    site_id: str = Field(min_length=1, max_length=20)
    site_type: str
    site_name: str
    location: str
    capacity_kw: float = Field(gt=0)
    status: str


class ReadingKey(BaseModel):
    """Clé minimale d'une mesure : ce qu'il faut pour l'écrire en bronze."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    site_id: str = Field(min_length=1, max_length=20)
    timestamp: UtcDatetime
