"""Client HTTP pour l'API Mock EnerVision (source de données IoT simulées).

Les fonctions lèvent ``requests.RequestException`` en cas d'échec au lieu de
renvoyer une valeur vide : l'appelant doit pouvoir distinguer « rien de
nouveau » d'« API injoignable » (une liste d'alertes vide ne doit pas fermer
toutes les alertes en cours).
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

from common.config import get_settings
from etl.schemas import SiteInfo

logger = logging.getLogger(__name__)

# Nombre maximal de mesures par appel à /api/v1/readings
READINGS_MAX_LIMIT = 1000

# Retry automatique sur les erreurs réseau transitoires (502, 503, 504).
# Pas de retry sur les 4xx : la requête est fausse, la rejouer ne sert à rien.
_retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])


@lru_cache
def _session() -> requests.Session:
    """Session partagée : réutilise les connexions (keep-alive) d'un appel à l'autre."""
    s = requests.Session()
    s.mount("http://", HTTPAdapter(max_retries=_retry))
    s.mount("https://", HTTPAdapter(max_retries=_retry))
    return s


def _get(path: str, params: dict[str, Any] | None = None, timeout: int = 10) -> Any:
    url = f"{get_settings().mock_api_url}{path}"
    resp = _session().get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_sites() -> list[SiteInfo]:
    """GET /api/v1/sites — liste des sites industriels, validée."""
    return [SiteInfo.model_validate(site) for site in _get("/api/v1/sites")]


def get_current_reading(site_id: str) -> dict[str, Any]:
    """GET /api/v1/sites/{site_id}/current — mesure instantanée d'un site.

    Source de la collecte minute (``etl.collect``). L'horodatage renvoyé est
    sans fuseau (UTC dans les faits) et à la microseconde.
    """
    return _get(f"/api/v1/sites/{site_id}/current")


def get_alerts() -> list[dict[str, Any]]:
    """GET /api/v1/alerts — alertes actives remontées par l'API Mock.

    Attention : l'API les régénère au hasard à chaque appel, et ``alert_id``
    contient l'heure de l'appel. Il ne permet donc pas de dédoublonner.
    """
    return _get("/api/v1/alerts")


def get_readings_history(
    site_id: str,
    start_time: datetime,
    end_time: datetime,
    limit: int,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """GET /api/v1/readings — historique simulé d'un site sur [start_time, end_time[.

    Sert uniquement à l'amorçage d'une base neuve (``etl.bootstrap``) : l'API
    tire de nouvelles valeurs à chaque appel, sans lien avec /current. Ne pas
    l'utiliser pour la collecte temps réel ni pour combler un trou.

    L'API renvoie toujours ``limit`` points répartis uniformément sur la
    fenêtre : le pas vaut (end_time − start_time) / limit. C'est à l'appelant
    de choisir des bornes et un ``limit`` qui donnent le pas voulu.
    """
    if not 1 <= limit <= READINGS_MAX_LIMIT:
        raise ValueError(f"limit doit être entre 1 et {READINGS_MAX_LIMIT}")
    params = {
        "site_id": site_id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "limit": limit,
    }
    return _get("/api/v1/readings", params=params, timeout=timeout)


def get_sensor_status() -> dict[str, Any]:
    """GET /api/v1/sensors/status — état de santé des capteurs par site.

    Retourne un dict dont les clés sont les site_id et les valeurs décrivent
    chaque capteur avec les champs `status` (ok | failing) et
    `failing_until` (timestamp de rétablissement prévu, ou null).
    """
    return _get("/api/v1/sensors/status")
