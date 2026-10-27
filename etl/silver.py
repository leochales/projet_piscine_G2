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

Un site actif sans aucune mesure en bronze apparaît quand même en silver
(``no_reading``) à partir du premier passage qui le voit. Le travail d'un
passage est borné à MAX_MINUTES_PER_RUN minutes par site : un long retard
(site réactivé, historique ancien) est rattrapé sur plusieurs passages.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from common.db import get_engine
from common.logs import configure_logging
from etl.collect import load_declared_sites
from etl.grid import STEP, floor_to_step
from etl.schemas import EnergyReading

logger = logging.getLogger(__name__)

# Trou le plus long (en minutes consécutives) comblé par interpolation
MAX_IMPUTED_GAP = 5

# Minutes déjà en silver retraitées à chaque exécution
REPROCESS_MARGIN = timedelta(minutes=10)

# Dernière minute matérialisée quand bronze est en retard : now − SETTLE_DELAY.
# La collecte range sa mesure sur la minute du passage (horloge locale) et
# tourne juste avant silver ; on laisse une minute de marge à un passage lent
# avant de déclarer la minute manquante.
SETTLE_DELAY = timedelta(minutes=1)

# Minutes écrites au plus par site et par passage, marge de retraitement
# comprise (le contexte d'imputation, lu mais pas écrit, s'y ajoute). 8 jours :
# l'amorçage de 7 jours (etl.bootstrap.BOOTSTRAP_DEPTH) et les minutes
# collectées pendant qu'il tourne passent en un seul passage, soit ~11 500
# lignes (quelques secondes), bien en deçà de la minute du cron. Au-delà (site
# réactivé après des mois), le reste est traité aux passages suivants. Doit
# rester très supérieur à REPROCESS_MARGIN, sinon le rattrapage n'avance pas.
MAX_MINUTES_PER_RUN = 8 * 24 * 60

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

EXIT_ALL_SITES_FAILED = 1

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
    output_to: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[Rejection]]:
    """Construit les lignes silver de ``output_from`` à ``output_to`` (inclus).

    ``output_to`` vaut ``grid_end`` par défaut. Les minutes entre
    ``grid_start`` et ``output_from``, et entre ``output_to`` et ``grid_end``,
    servent de contexte à l'imputation et ne sont pas renvoyées.
    """
    if output_to is None:
        output_to = grid_end
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

    rows = [r for r in rows if output_from <= r["horodatage"] <= output_to]
    rejections = [r for r in rejections if output_from <= r.horodatage <= output_to]
    return rows, rejections


def _processing_range(
    conn: Connection, id_site: str, now: datetime
) -> tuple[datetime, datetime] | None:
    """Période à (re)traiter pour un site, au plus MAX_MINUTES_PER_RUN minutes.

    La période va jusqu'à ``now − SETTLE_DELAY`` même si bronze s'arrête
    avant, ou n'a encore aucune mesure : une collecte en panne, ou un site
    jamais collecté, apparaît en silver (``no_reading``) au lieu de rester
    invisible. Sans bronze ni silver, silver commence à cette minute.

    Silver reste d'un seul tenant, de sa première à sa dernière minute :
      - cas courant, il avance depuis sa dernière minute (moins la marge de
        retraitement) ;
      - si la première mesure de bronze manque en silver, ou n'y est qu'en
        ``no_reading`` (amorçage relancé après le début de la collecte,
        ``etl.bootstrap``), il repart de cette mesure. Si elle précède silver
        de plus d'un passage, il recule d'un passage à la fois, en recouvrant
        la marge de retraitement au début de silver.
    Le reste de la période (rattrapage) est traité aux passages suivants.

    Les requêtes passent par les index (id_site, horodatage) et s'arrêtent à
    la première ligne trouvée : leur coût ne dépend pas du volume du site.
    """
    sql = text("""
        WITH b AS (
            SELECT
                (
                    SELECT horodatage FROM bronze.raw_readings
                    WHERE id_site = :id_site
                      AND horodatage = date_trunc('minute', horodatage)
                    ORDER BY horodatage LIMIT 1
                ) AS bronze_first,
                (
                    SELECT horodatage FROM bronze.raw_readings
                    WHERE id_site = :id_site
                      AND horodatage = date_trunc('minute', horodatage)
                    ORDER BY horodatage DESC LIMIT 1
                ) AS bronze_last
        )
        SELECT
            (SELECT min(horodatage) FROM silver.silver_readings
             WHERE id_site = :id_site) AS silver_first,
            (SELECT max(horodatage) FROM silver.silver_readings
             WHERE id_site = :id_site) AS silver_last,
            b.bronze_first,
            b.bronze_last,
            EXISTS (
                SELECT 1 FROM silver.silver_readings AS s
                WHERE s.id_site = :id_site
                  AND s.horodatage = b.bronze_first
                  AND s.bronze_id IS NOT NULL
            ) AS bronze_first_in_silver
        FROM b
    """)
    r = conn.execute(sql, {"id_site": id_site}).one()
    run = (MAX_MINUTES_PER_RUN - 1) * STEP
    target = floor_to_step(now - SETTLE_DELAY)
    if r.bronze_last is not None:
        target = max(target, r.bronze_last)

    if r.silver_last is None:
        start = r.bronze_first if r.bronze_first is not None else target
    elif (
        r.bronze_first is not None
        and r.bronze_first <= r.silver_last
        and not r.bronze_first_in_silver
    ):
        # Recul d'un passage au plus, en gardant la marge sur le début de
        # silver : la fin de la période (start + run) recouvre silver_first
        start = max(r.bronze_first, r.silver_first - run + REPROCESS_MARGIN)
        if start > r.bronze_first:
            logger.info(
                "site %s : rattrapage de l'historique, silver recule à %s "
                "(bronze commence à %s)",
                id_site,
                start.isoformat(timespec="minutes"),
                r.bronze_first.isoformat(timespec="minutes"),
            )
    else:
        start = max(r.silver_last - REPROCESS_MARGIN, r.silver_first)

    end = min(target, start + run)
    # Dernière minute de silver après ce passage
    front = end if r.silver_last is None else max(r.silver_last, end)
    if front < target:
        logger.info(
            "site %s : rattrapage, silver à jour jusqu'à %s (retard %s)",
            id_site,
            front.isoformat(timespec="minutes"),
            target - front,
        )
    if start > end:
        return None
    return start, end


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


def transform_site(
    conn: Connection, id_site: str, capacite_kw: float, now: datetime
) -> int:
    """Met à jour silver pour un site. Retourne le nombre de lignes écrites."""
    period = _processing_range(conn, id_site, now)
    if period is None:
        return 0
    start, end = period
    # Contexte d'imputation des deux côtés : la fin de la période peut être
    # suivie de minutes déjà en silver (rattrapage de l'historique)
    context = (MAX_IMPUTED_GAP + 1) * STEP
    bronze = _load_bronze(conn, id_site, start - context, end + context)
    rows, rejections = build_silver_rows(
        id_site,
        capacite_kw,
        start - context,
        end + context,
        bronze,
        output_from=start,
        output_to=end,
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


def transform(now: datetime | None = None) -> dict[str, int]:
    """Transforme bronze → silver pour tous les sites actifs déclarés."""
    now = now or datetime.now(tz=UTC)
    with get_engine().connect() as conn:
        declared = load_declared_sites(conn)

    total = sites_in_error = 0
    for id_site, capacite_kw in declared.items():
        # Une transaction par site : un site en erreur n'annule pas les autres
        try:
            with get_engine().begin() as conn:
                n = transform_site(conn, id_site, capacite_kw, now)
        except SQLAlchemyError as exc:
            logger.error("site %s : échec de la transformation — %s", id_site, exc)
            sites_in_error += 1
            continue
        except Exception:
            # Une erreur imprévue sur un site n'arrête pas les autres
            logger.exception("site %s : erreur inattendue", id_site)
            sites_in_error += 1
            continue
        logger.info("site=%s : %d ligne(s) silver écrites", id_site, n)
        total += n

    # Tous les sites en échec : code non nul pour que l'ordonnanceur le voie
    if declared and sites_in_error == len(declared):
        logger.error("tous les sites ont échoué — exit %d", EXIT_ALL_SITES_FAILED)
        sys.exit(EXIT_ALL_SITES_FAILED)
    return {
        "sites": len(declared),
        "rows_written": total,
        "sites_in_error": sites_in_error,
    }


if __name__ == "__main__":
    configure_logging("etl")
    transform()
