"""Client HTTP pour l'API Mock EnerVision (source de données IoT simulées)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

from common.config import get_settings

logger = logging.getLogger(__name__)

# Retry automatique sur les erreurs réseau transitoires (503, 502, timeout)
_retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("http://", HTTPAdapter(max_retries=_retry))
    s.mount("https://", HTTPAdapter(max_retries=_retry))
    return s


def get_sites() -> list[dict[str, Any]]:
    """GET /api/v1/sites — liste des 7 sites industriels."""
    url = f"{get_settings().mock_api_url}/api/v1/sites"
    try:
        resp = _session().get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("get_sites() failed: %s", exc)
        return []


def get_current_reading(site_id: str) -> dict[str, Any] | None:
    """GET /api/v1/sites/{site_id}/current — dernière mesure d'un site."""
    url = f"{get_settings().mock_api_url}/api/v1/sites/{site_id}/current"
    try:
        resp = _session().get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("get_current_reading(%s) failed: %s", site_id, exc)
        return None


def get_alerts() -> list[dict[str, Any]]:
    """GET /api/v1/alerts — alertes actives remontées par l'API Mock."""
    url = f"{get_settings().mock_api_url}/api/v1/alerts"
    try:
        resp = _session().get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("get_alerts() failed: %s", exc)
        return []


def get_readings_history(
    site_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """GET /api/v1/readings — historique des lectures sur une période.

    Utilisé pour l'amorçage (bootstrap) de Bronze au premier démarrage.
    Le MOOC accepte un maximum de 1000 résultats par appel.

    Args:
        site_id:    Filtrer sur un site précis. None = tous les sites.
        start_time: Début de la période (ISO 8601). Défaut API : 24h avant end_time.
        end_time:   Fin de la période (ISO 8601). Défaut API : maintenant.
        limit:      Nombre de résultats max (1–1000).
    """
    url = f"{get_settings().mock_api_url}/api/v1/readings"
    params: dict[str, Any] = {"limit": min(limit, 1000)}
    if site_id:
        params["site_id"] = site_id
    if start_time:
        params["start_time"] = start_time.isoformat()
    if end_time:
        params["end_time"] = end_time.isoformat()
    try:
        resp = _session().get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("get_readings_history(site=%s) failed: %s", site_id, exc)
        return []


def get_sensor_status() -> dict[str, Any]:
    """GET /api/v1/sensors/status — état de santé des capteurs par site.

    Retourne un dict dont les clés sont les site_id et les valeurs décrivent
    chaque capteur avec les champs `status` (ok | failing) et
    `failing_until` (timestamp de rétablissement prévu, ou null).

    Utilisé par aggregate.py pour enrichir gold.etat_capteur avec les
    informations de l'API plutôt que de les dériver de Silver.
    """
    url = f"{get_settings().mock_api_url}/api/v1/sensors/status"
    try:
        resp = _session().get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("get_sensor_status() failed: %s", exc)
        return {}
