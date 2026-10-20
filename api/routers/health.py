"""Santé du service, utilisée par Docker, Traefik et la supervision."""

from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from common.db import check_database

router = APIRouter(tags=["santé"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unreachable"]


def database_status() -> bool:
    return check_database()


@router.get(
    "/health",
    summary="État de l'API et de la base",
    responses={503: {"model": HealthResponse, "description": "Base injoignable"}},
)
def health(
    response: Response, database_ok: bool = Depends(database_status)
) -> HealthResponse:
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="unreachable")
    return HealthResponse(status="ok", database="ok")
