"""Contrat des réponses de l'API Mock (OpenAPI v1.1.0), validé avec Pydantic.

Deux niveaux de validation :
  - ``ReadingKey`` à l'extraction : seuls ``site_id`` et ``timestamp`` sont
    contrôlés, car ils forment la clé de bronze. Le reste du payload est
    stocké tel quel, même s'il est mal formé, pour pouvoir être analysé ;
  - ``EnergyReading`` au passage bronze → silver : contrôle complet. Une
    mesure qui échoue part en quarantaine (``silver.rejected_readings``).

Les plages physiques (tension, facteur de puissance…) ne sont pas vérifiées
ici : une valeur hors plage ne rejette pas la mesure, elle est mise à NULL
en silver avec une raison (voir ``etl.silver``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _force_utc(ts: datetime) -> datetime:
    # /readings renvoie "…Z" ; /current et /alerts des dates sans fuseau,
    # qui sont en UTC dans les faits
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_force_utc)]

NullReason = Literal[
    "consumption_sensor_failure",
    "electrical_sensor_failure",
    "temperature_sensor_failure",
    "humidity_sensor_failure",
    "network_loss",
]

DataQuality = Literal["good", "partial", "degraded", "critical"]


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


class EnergyReading(ReadingKey):
    """GET /api/v1/sites/{site_id}/current : une mesure complète.

    ``consumption_kwh`` est volontairement absent : l'API le renvoie toujours
    égal à ``consumption_kw``, ce n'est pas une énergie. Les kWh sont
    calculés en gold.
    """

    site_type: str
    consumption_kw: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    power_factor: float | None = None
    temperature_celsius: float | None = None
    humidity_percent: float | None = None
    null_reasons: list[NullReason] = []
    data_quality: DataQuality = "good"


SensorName = Literal["consumption", "electrical", "temperature", "humidity", "network"]


class SensorState(BaseModel):
    """État d'un capteur dans GET /api/v1/sensors/status."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["ok", "failing"]
    # Date de rétablissement prévue (sans fuseau dans l'API : UTC)
    failing_until: UtcDatetime | None = None


class SiteSensors(BaseModel):
    """GET /api/v1/sensors/status : capteurs d'un site, sous sa clé site_id.

    ``overall`` vaut ``degraded`` dès qu'un capteur est en panne, et
    ``critical`` en cas de perte réseau (aucune donnée transmise).
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    sensors: dict[SensorName, SensorState]
    overall: Literal["ok", "degraded", "critical"]
