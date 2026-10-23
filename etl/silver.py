"""ETL — Transformation bronze → silver.

Pour chaque site actif, silver contient une ligne par minute de la grille,
y compris les minutes sans mesure en bronze (``bronze_id`` NULL). Un trou de
collecte devient ainsi visible et peut être imputé.

Chaque ligne bronze est :
  1. validée par ``EnergyReading`` (Pydantic). En cas d'échec, elle part en
     quarantaine dans ``silver.rejected_readings`` et la minute est traitée
     comme manquante ;
  2. contrôlée par plages physiques (``RANGES``) : une valeur hors plage est
     mise à NULL avec la raison ``<champ>_out_of_range``. C'est fait ici, en
     Python, pour qu'une seule valeur aberrante ne fasse pas échouer tout le
     lot sur un CHECK de la table ;
  3. complétée : seule la consommation est imputée, par interpolation
     linéaire, et seulement pour les trous de MAX_IMPUTED_GAP minutes au
     plus. La valeur brute reste dans ``consumption_kw_raw``.

L'interpolation utilise la mesure suivante : elle convient pour calculer la
consommation d'une heure passée, pas pour des variables d'entrée du modèle
(qui ne connaît pas le futur au moment de prédire). Le service modèle doit
partir de ``consumption_kw_raw`` et de ``imputation_method``.

Les valeurs au-dessus de la capacité sont conservées (``load_percent`` peut
dépasser 100) : ce sont les pics qu'on veut détecter. Seules celles au-delà
de MAX_LOAD_RATIO × capacité sont jugées physiquement aberrantes.

Rejouable : chaque exécution retraite les REPROCESS_MARGIN dernières
minutes déjà en silver (upsert), ce qui impute un trou dès que la mesure qui
le suit arrive.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from common.db import get_engine
from common.logs import configure_logging
from etl.collect import STEP, load_declared_sites
from etl.schemas import EnergyReading

logger = logging.getLogger(__name__)

# Trou le plus long (en minutes consécutives) comblé par interpolation
MAX_IMPUTED_GAP = 5

# Minutes déjà en silver retraitées à chaque exécution
REPROCESS_MARGIN = timedelta(minutes=10)

# Consommation au-delà de ce multiple de la capacité : capteur aberrant
MAX_LOAD_RATIO = 2.0

# Plages physiques plausibles (bornes incluses, None = pas de borne)
RANGES: dict[str, tuple[float | None, float | None]] = {
    "voltage_v": (360.0, 440.0),  # 400 V triphasé ± 10 % (EN 50160)
    "current_a": (0.0, 10_000.0),
    "power_factor": (0.0, 1.0),
    "temperature_celsius": (-40.0, 60.0),
    "humidity_percent": (0.0, 100.0),
}

NO_READING = "no_reading"
REJECTED_READING = "rejected_reading"


@dataclass(frozen=True)
class BronzeRow:
    id: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class Rejection:
    bronze_id: int
    horodatage: datetime
    errors: list[dict[str, Any]]


def _in_range(value: float, bounds: tuple[float | None, float | None]) -> bool:
    low, high = bounds
    return (low is None or value >= low) and (high is None or value <= high)


def _missing_row(
    id_site: str, ts: datetime, bronze_id: int | None, reason: str
) -> dict[str, Any]:
    return {
        "id_site": id_site,
        "horodatage": ts,
        "bronze_id": bronze_id,
        "consumption_kw_raw": None,
        "voltage_v": None,
        "current_a": None,
        "power_factor": None,
        "temperature_celsius": None,
        "humidity_percent": None,
        "data_quality": "critical",
        "null_reasons": [reason],
    }


def clean_reading(
    id_site: str, ts: datetime, bronze: BronzeRow, capacite_kw: float
) -> tuple[dict[str, Any], Rejection | None]:
    """Valide une mesure bronze et applique les plages physiques."""
    try:
        reading = EnergyReading.model_validate(bronze.payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False)
        # Les erreurs Pydantic peuvent contenir des valeurs non sérialisables
        errors = json.loads(json.dumps(errors, default=str))
        return _missing_row(id_site, ts, bronze.id, REJECTED_READING), Rejection(
            bronze.id, ts, errors
        )

    reasons: list[str] = list(reading.null_reasons)
    values: dict[str, float | None] = {}
    bounds = dict(RANGES, consumption_kw=(0.0, MAX_LOAD_RATIO * capacite_kw))
    for field, field_bounds in bounds.items():
        value = getattr(reading, field)
        if value is not None and not _in_range(value, field_bounds):
            reasons.append(f"{field}_out_of_range")
            value = None
        values[field] = value

    quality = reading.data_quality
    if quality == "good" and len(reasons) > len(reading.null_reasons):
        quality = "partial"

    return {
        "id_site": id_site,
        "horodatage": ts,
        "bronze_id": bronze.id,
        "consumption_kw_raw": values["consumption_kw"],
        "voltage_v": values["voltage_v"],
        "current_a": values["current_a"],
        "power_factor": values["power_factor"],
        "temperature_celsius": values["temperature_celsius"],
        "humidity_percent": values["humidity_percent"],
        "data_quality": quality,
        "null_reasons": reasons,
    }, None


def impute_consumption(raw: list[float | None]) -> list[tuple[float | None, str]]:
    """Interpolation linéaire des trous de MAX_IMPUTED_GAP valeurs au plus.

    Un trou n'est comblé que s'il est encadré par deux valeurs connues.
    Retourne, pour chaque point, (valeur finale, méthode d'imputation).
    """
    result: list[tuple[float | None, str]] = [
        (v, "none") if v is not None else (None, "none") for v in raw
    ]
    i = 0
    while i < len(raw):
        if raw[i] is not None:
            i += 1
            continue
        gap_start = i
        while i < len(raw) and raw[i] is None:
            i += 1
        gap_len = i - gap_start
        left = raw[gap_start - 1] if gap_start > 0 else None
        right = raw[i] if i < len(raw) else None
        if left is None or right is None or gap_len > MAX_IMPUTED_GAP:
            continue
        for k in range(gap_len):
            frac = (k + 1) / (gap_len + 1)
            value = round(left + (right - left) * frac, 2)
            result[gap_start + k] = (value, "linear_interpolation")
    return result


def build_silver_rows(
    id_site: str,
    capacite_kw: float,
    grid_start: datetime,
    grid_end: datetime,
    bronze: dict[datetime, BronzeRow],
    output_from: datetime,
) -> tuple[list[dict[str, Any]], list[Rejection]]:
    """Construit les lignes silver de ``output_from`` à ``grid_end`` (inclus).

    Les minutes entre ``grid_start`` et ``output_from`` servent de contexte
    à l'imputation et ne sont pas renvoyées.
    """
    rows: list[dict[str, Any]] = []
    rejections: list[Rejection] = []
    ts = grid_start
    while ts <= grid_end:
        found = bronze.get(ts)
        if found is None:
            rows.append(_missing_row(id_site, ts, None, NO_READING))
        else:
            row, rejection = clean_reading(id_site, ts, found, capacite_kw)
            rows.append(row)
            if rejection is not None:
                rejections.append(rejection)
        ts += STEP

    imputed = impute_consumption([r["consumption_kw_raw"] for r in rows])
    for row, (value, method) in zip(rows, imputed, strict=True):
        row["consumption_kw_imputed"] = value
        row["imputation_method"] = method
        row["load_percent"] = (
            None if value is None else round(100 * value / capacite_kw, 2)
        )

    rows = [r for r in rows if r["horodatage"] >= output_from]
    rejections = [r for r in rejections if r.horodatage >= output_from]
    return rows, rejections


def _processing_range(
    conn: Connection, id_site: str
) -> tuple[datetime, datetime] | None:
    """Période à (re)traiter pour un site, ou None s'il n'y a rien en bronze."""
    sql = text("""
        SELECT
            (SELECT MAX(horodatage) FROM silver.silver_readings
             WHERE id_site = :id_site) AS silver_last,
            MIN(horodatage) AS bronze_first,
            MAX(horodatage) AS bronze_last
        FROM bronze.raw_readings
        WHERE id_site = :id_site
          AND horodatage = date_trunc('minute', horodatage)
    """)
    r = conn.execute(sql, {"id_site": id_site}).one()
    if r.bronze_last is None:
        return None
    start = r.silver_last - REPROCESS_MARGIN if r.silver_last else r.bronze_first
    start = max(start, r.bronze_first)
    if start > r.bronze_last:
        return None
    return start, r.bronze_last


def _load_bronze(
    conn: Connection, id_site: str, start: datetime, end: datetime
) -> dict[datetime, BronzeRow]:
    """Mesures bronze sur la grille (hh:mm:00) entre start et end inclus.

    Les lignes hors grille (ancienne collecte à pas variable) sont ignorées.
    """
    sql = text("""
        SELECT id, horodatage, payload
        FROM bronze.raw_readings
        WHERE id_site = :id_site
          AND horodatage BETWEEN :start AND :end
          AND horodatage = date_trunc('minute', horodatage)
    """)
    params = {"id_site": id_site, "start": start, "end": end}
    return {r.horodatage: BronzeRow(r.id, r.payload) for r in conn.execute(sql, params)}


UPSERT_SILVER = text("""
    INSERT INTO silver.silver_readings (
        id_site, horodatage, bronze_id,
        consumption_kw_raw, consumption_kw_imputed, imputation_method,
        voltage_v, current_a, power_factor,
        temperature_celsius, humidity_percent, load_percent,
        data_quality, null_reasons
    )
    VALUES (
        :id_site, :horodatage, :bronze_id,
        :consumption_kw_raw, :consumption_kw_imputed, :imputation_method,
        :voltage_v, :current_a, :power_factor,
        :temperature_celsius, :humidity_percent, :load_percent,
        :data_quality, CAST(:null_reasons AS text[])
    )
    ON CONFLICT (id_site, horodatage) DO UPDATE SET
        bronze_id = EXCLUDED.bronze_id,
        consumption_kw_raw = EXCLUDED.consumption_kw_raw,
        consumption_kw_imputed = EXCLUDED.consumption_kw_imputed,
        imputation_method = EXCLUDED.imputation_method,
        voltage_v = EXCLUDED.voltage_v,
        current_a = EXCLUDED.current_a,
        power_factor = EXCLUDED.power_factor,
        temperature_celsius = EXCLUDED.temperature_celsius,
        humidity_percent = EXCLUDED.humidity_percent,
        load_percent = EXCLUDED.load_percent,
        data_quality = EXCLUDED.data_quality,
        null_reasons = EXCLUDED.null_reasons,
        processed_at = now()
""")

UPSERT_REJECTION = text("""
    INSERT INTO silver.rejected_readings (bronze_id, id_site, horodatage, errors)
    VALUES (:bronze_id, :id_site, :horodatage, CAST(:errors AS jsonb))
    ON CONFLICT (bronze_id) DO UPDATE SET
        errors = EXCLUDED.errors,
        rejected_at = now()
""")


def transform_site(conn: Connection, id_site: str, capacite_kw: float) -> int:
    """Met à jour silver pour un site. Retourne le nombre de lignes écrites."""
    period = _processing_range(conn, id_site)
    if period is None:
        return 0
    start, end = period
    context_start = start - (MAX_IMPUTED_GAP + 1) * STEP
    bronze = _load_bronze(conn, id_site, context_start, end)
    rows, rejections = build_silver_rows(
        id_site, capacite_kw, context_start, end, bronze, output_from=start
    )
    if rows:
        conn.execute(UPSERT_SILVER, rows)
    if rejections:
        conn.execute(
            UPSERT_REJECTION,
            [
                {
                    "bronze_id": r.bronze_id,
                    "id_site": id_site,
                    "horodatage": r.horodatage,
                    "errors": json.dumps(r.errors),
                }
                for r in rejections
            ],
        )
        logger.warning(
            "site %s : %d mesure(s) en quarantaine", id_site, len(rejections)
        )
    return len(rows)


def transform() -> dict[str, int]:
    """Transforme bronze → silver pour tous les sites actifs déclarés."""
    with get_engine().connect() as conn:
        declared = load_declared_sites(conn)

    total = sites_in_error = 0
    for id_site, capacite_kw in declared.items():
        # Une transaction par site : un site en erreur n'annule pas les autres
        try:
            with get_engine().begin() as conn:
                n = transform_site(conn, id_site, capacite_kw)
        except SQLAlchemyError as exc:
            logger.error("site %s : échec de la transformation — %s", id_site, exc)
            sites_in_error += 1
            continue
        logger.info("site=%s : %d ligne(s) silver écrites", id_site, n)
        total += n
    return {
        "sites": len(declared),
        "rows_written": total,
        "sites_in_error": sites_in_error,
    }


if __name__ == "__main__":
    configure_logging("etl")
    transform()
