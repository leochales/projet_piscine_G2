"""ETL — Couche Silver.

Lit les lignes Bronze non encore traitées, applique :
  - Extraction des champs depuis le payload JSONB (pas de jointure dim_sites)
  - Imputation des valeurs NULL (consumption_kw)
  - Calcul des features ML (temporelles + lags)
  - Calcul de load_percent (variable cible normalisée)
  - Score de qualité

Et insère dans silver.silver_readings.

Lecture du JSONB Bronze :
  payload->>'_site'  → métadonnées du site (capacity_kw, site_type, …)
  payload->>champ    → valeurs de la mesure brute
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text

from common.db import get_engine

logger = logging.getLogger(__name__)

# Seuil : au-delà de N NULLs consécutifs, on ne peut pas interpoler fiablement
MAX_IMPUTABLE_GAP = 5


def _fetch_unprocessed() -> pd.DataFrame:
    """Récupère les lignes Bronze pas encore dans Silver.

    Extrait les champs nécessaires directement depuis le payload JSONB —
    pas de jointure vers une table dim_sites.
    """
    sql = text("""
        SELECT
            r.id                                            AS bronze_id,
            r.timestamp,
            r.site_id,
            r.data_quality,
            -- Métadonnées du site dénormalisées dans le payload
            (r.payload -> '_site' ->> 'capacity_kw')::int  AS capacity_kw,
            -- Mesures brutes
            (r.payload ->> 'consumption_kw')::float8       AS consumption_kw,
            (r.payload ->> 'consumption_kwh')::float8      AS consumption_kwh,
            (r.payload ->> 'voltage_v')::float8            AS voltage_v,
            (r.payload ->> 'current_a')::float8            AS current_a,
            (r.payload ->> 'power_factor')::float8         AS power_factor,
            (r.payload ->> 'temperature_celsius')::float8  AS temperature_celsius,
            (r.payload ->> 'humidity_percent')::float8     AS humidity_percent
        FROM bronze.raw_readings r
        WHERE r.id NOT IN (
            SELECT bronze_id FROM silver.silver_readings
        )
        ORDER BY r.site_id, r.timestamp
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn)


def _fetch_recent_silver(site_id: str, n: int = 200) -> pd.DataFrame:
    """Récupère les N dernières lignes Silver d'un site (pour calculer les lags)."""
    sql = text("""
        SELECT timestamp, load_percent
        FROM silver.silver_readings
        WHERE site_id = :site_id
        ORDER BY timestamp DESC
        LIMIT :n
    """)
    with get_engine().connect() as conn:
        df = pd.read_sql(sql, conn, params={"site_id": site_id, "n": n})
    return df.sort_values("timestamp")


def _impute(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Impute les NULLs d'une série temporelle.

    Retourne :
      - imputed   : série avec NULLs remplacés
      - is_imputed: booléen par ligne
      - method    : méthode utilisée par ligne ('none' | 'linear_interpolation' | 'forward_fill')
    """
    is_null = series.isna()
    imputed = series.copy()
    method = pd.Series(["none"] * len(series), index=series.index)

    if not is_null.any():
        return imputed, is_null, method

    # Interpolation linéaire sur les petits trous
    interp = series.interpolate(method="linear", limit=MAX_IMPUTABLE_GAP)
    mask_interp = is_null & interp.notna()
    imputed[mask_interp] = interp[mask_interp]
    method[mask_interp] = "linear_interpolation"

    # Forward fill pour les trous restants (bord de série)
    ffill = imputed.ffill()
    mask_ffill = imputed.isna() & ffill.notna()
    imputed[mask_ffill] = ffill[mask_ffill]
    method[mask_ffill] = "forward_fill"

    # Ce qui reste NULL est laissé NULL (is_imputed = True quand on a pu imputer)
    return imputed, is_null & imputed.notna(), method


def _quality_score(data_quality: str) -> float:
    return {"good": 1.0, "partial": 0.7, "degraded": 0.4, "critical": 0.0}.get(
        data_quality, 0.5
    )


def _compute_lags(
    row_ts: pd.Timestamp,
    site_id: str,
    silver_history: pd.DataFrame,
) -> tuple[float | None, float | None, float | None]:
    """Calcule load_lag_1h, load_lag_24h, load_rolling_3h depuis l'historique Silver."""
    if silver_history.empty:
        return None, None, None

    hist = silver_history.copy()
    hist["timestamp"] = pd.to_datetime(hist["timestamp"], utc=True)
    hist = hist.set_index("timestamp").sort_index()

    def _nearest(target: pd.Timestamp, window_sec: int = 180) -> float | None:
        lo = target - pd.Timedelta(seconds=window_sec)
        hi = target + pd.Timedelta(seconds=window_sec)
        sub = hist.loc[lo:hi, "load_percent"].dropna()
        return float(sub.iloc[-1]) if not sub.empty else None

    lag_1h = _nearest(row_ts - pd.Timedelta(hours=1))
    lag_24h = _nearest(row_ts - pd.Timedelta(hours=24))

    lo3 = row_ts - pd.Timedelta(hours=3)
    rolling_vals = hist.loc[lo3:row_ts, "load_percent"].dropna()
    rolling_3h = float(rolling_vals.mean()) if not rolling_vals.empty else None

    return lag_1h, lag_24h, rolling_3h


def _process_site(df_site: pd.DataFrame) -> list[dict]:
    """Transforme les lignes Bronze d'un site en lignes Silver prêtes à insérer.

    capacity_kw est lu depuis la colonne extraite du JSONB (payload._site).
    """
    site_id = df_site["site_id"].iloc[0]
    capacity_kw = df_site["capacity_kw"].iloc[0]
    silver_hist = _fetch_recent_silver(site_id)

    # Imputation vectorisée sur toute la fenêtre du site
    imputed_vals, is_imputed_mask, method_vals = _impute(df_site["consumption_kw"])

    rows = []
    for i, (_, row) in enumerate(df_site.iterrows()):
        ts = pd.Timestamp(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")

        consumption_kw_imputed = imputed_vals.iloc[i]
        # pandas renvoie float('nan') — pas None — quand l'imputation échoue.
        # NaN est not None → passe le guard → insère NaN → viole chk_silver_load.
        if pd.isna(consumption_kw_imputed):
            consumption_kw_imputed = None
        load_percent = (
            float(consumption_kw_imputed) / float(capacity_kw) * 100.0
            if consumption_kw_imputed is not None and capacity_kw and capacity_kw > 0
            else None
        )

        lag_1h, lag_24h, rolling_3h = _compute_lags(ts, site_id, silver_hist)

        rows.append(
            {
                "bronze_id": int(row["bronze_id"]),
                "timestamp": ts.to_pydatetime(),
                "site_id": site_id,
                "consumption_kw_raw": row["consumption_kw"]
                if not pd.isna(row["consumption_kw"])
                else None,
                "consumption_kw_imputed": float(consumption_kw_imputed)
                if consumption_kw_imputed is not None
                else None,
                "is_imputed": bool(is_imputed_mask.iloc[i]),
                "imputation_method": method_vals.iloc[i],
                "consumption_kwh": row["consumption_kwh"]
                if not pd.isna(row["consumption_kwh"])
                else None,
                "voltage_v": row["voltage_v"]
                if not pd.isna(row["voltage_v"])
                else None,
                "current_a": row["current_a"]
                if not pd.isna(row["current_a"])
                else None,
                "power_factor": row["power_factor"]
                if not pd.isna(row["power_factor"])
                else None,
                "temperature_celsius": row["temperature_celsius"]
                if not pd.isna(row["temperature_celsius"])
                else None,
                "humidity_percent": row["humidity_percent"]
                if not pd.isna(row["humidity_percent"])
                else None,
                "data_quality": row["data_quality"],
                "quality_score": _quality_score(row["data_quality"]),
                "hour_of_day": ts.hour,
                "day_of_week": ts.weekday(),
                "is_weekend": ts.weekday() >= 5,
                "month": ts.month,
                "load_percent": load_percent,
                "load_lag_1h": lag_1h,
                "load_lag_24h": lag_24h,
                "load_rolling_3h": rolling_3h,
            }
        )
    return rows


def _insert_silver(rows: list[dict]) -> int:
    if not rows:
        return 0

    sql = text("""
        INSERT INTO silver.silver_readings (
            bronze_id, timestamp, site_id,
            consumption_kw_raw, consumption_kw_imputed,
            is_imputed, imputation_method,
            consumption_kwh, voltage_v, current_a, power_factor,
            temperature_celsius, humidity_percent,
            data_quality, quality_score,
            hour_of_day, day_of_week, is_weekend, month,
            load_percent, load_lag_1h, load_lag_24h, load_rolling_3h
        ) VALUES (
            :bronze_id, :timestamp, :site_id,
            :consumption_kw_raw, :consumption_kw_imputed,
            :is_imputed, :imputation_method,
            :consumption_kwh, :voltage_v, :current_a, :power_factor,
            :temperature_celsius, :humidity_percent,
            :data_quality, :quality_score,
            :hour_of_day, :day_of_week, :is_weekend, :month,
            :load_percent, :load_lag_1h, :load_lag_24h, :load_rolling_3h
        )
        ON CONFLICT (site_id, timestamp) DO NOTHING
    """)

    with get_engine().begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def run() -> dict[str, int]:
    """Point d'entrée : nettoie et enrichit toutes les lignes Bronze non traitées."""
    logger.info("[CLEAN] Démarrage")

    df = _fetch_unprocessed()
    if df.empty:
        logger.info("[CLEAN] Rien à traiter")
        return {"processed": 0}

    logger.info("[CLEAN] %d ligne(s) Bronze à traiter", len(df))

    all_rows: list[dict] = []
    for site_id, df_site in df.groupby("site_id"):
        site_rows = _process_site(df_site)
        all_rows.extend(site_rows)

    inserted = _insert_silver(all_rows)
    logger.info("[CLEAN] %d ligne(s) insérées dans Silver", inserted)
    return {"processed": inserted}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run()