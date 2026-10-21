"""ETL — Couche Gold.

Calcule les agrégats métier depuis Silver et les écrit dans :
  - gold.gold_latest      (dernière mesure par site — UPSERT, toujours)
  - gold.gold_hourly      (agrégats horaires — INSERT, toutes les heures à :00)
  - gold.gold_alerts      (alertes dépassement seuil + alertes API Mock)
  - gold.etat_capteur     (statut des capteurs — UPSERT, toujours)
  - gold.recommandation   (recommandations liées aux alertes — INSERT)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from common.config import get_settings
from common.db import get_engine
from etl.api_client import get_alerts, get_sensor_status

logger = logging.getLogger(__name__)

# Seuils d'alerte (% de charge)
ALERT_THRESHOLD_HIGH = 90.0  # high
ALERT_THRESHOLD_CRITICAL = 110.0  # critical (surcharge)

# Seuil de pic prévu en prédiction (% de charge)
ALERT_THRESHOLD_PIC = 85.0


def _upsert_gold_latest() -> int:
    """UPSERT gold.gold_latest depuis la dernière mesure Silver par site.

    Joint bronze pour récupérer null_reasons ; Silver expose power_factor
    (facteur_puissance) directement.
    """
    sql = text("""
        INSERT INTO gold.gold_latest (
            site_id, site_name, site_type, capacity_kw,
            consumption_kw, load_percent, data_quality,
            temperature_celsius, humidity_percent,
            facteur_puissance, null_reasons,
            last_reading_at, updated_at
        )
        SELECT DISTINCT ON (s.site_id)
            s.site_id,
            b.payload -> '_site' ->> 'site_name'                          AS site_name,
            b.payload -> '_site' ->> 'site_type'                          AS site_type,
            (b.payload -> '_site' ->> 'capacity_kw')::int                 AS capacity_kw,
            s.consumption_kw_imputed,
            s.load_percent,
            s.data_quality,
            s.temperature_celsius,
            s.humidity_percent,
            s.power_factor,
            (SELECT ARRAY_AGG(x)
             FROM jsonb_array_elements_text(b.payload -> 'null_reasons') x) AS null_reasons,
            s.timestamp,
            NOW()
        FROM silver.silver_readings s
        JOIN bronze.raw_readings b ON b.id = s.bronze_id
        ORDER BY s.site_id, s.timestamp DESC
        ON CONFLICT (site_id) DO UPDATE SET
            site_name           = EXCLUDED.site_name,
            site_type           = EXCLUDED.site_type,
            capacity_kw         = EXCLUDED.capacity_kw,
            consumption_kw      = EXCLUDED.consumption_kw,
            load_percent        = EXCLUDED.load_percent,
            data_quality        = EXCLUDED.data_quality,
            temperature_celsius = EXCLUDED.temperature_celsius,
            humidity_percent    = EXCLUDED.humidity_percent,
            facteur_puissance   = EXCLUDED.facteur_puissance,
            null_reasons        = EXCLUDED.null_reasons,
            last_reading_at     = EXCLUDED.last_reading_at,
            updated_at          = EXCLUDED.updated_at
        WHERE EXCLUDED.last_reading_at > gold.gold_latest.last_reading_at
    """)
    with get_engine().begin() as conn:
        result = conn.execute(sql)
    return result.rowcount


def _insert_hourly(hour_start: datetime) -> int:
    """Insère les agrégats de l'heure `hour_start` dans gold.gold_hourly.

    consommation_kwh = avg_kw × (reading_count / 60)
    Tient compte des trous de mesure : une heure avec 30 mesures
    contribue la moitié d'une heure pleine.

    cout_eur = consommation_kwh × tarif_kwh_eur  (configuré via TARIF_KWH_EUR dans .env)
    """
    tarif = get_settings().tarif_kwh_eur

    sql = text("""
        INSERT INTO gold.gold_hourly (
            site_id, hour_start,
            avg_consumption_kw, max_consumption_kw, min_consumption_kw,
            avg_load_percent,
            avg_temperature_celsius, avg_humidity_percent,
            consommation_kwh, cout_eur,
            reading_count, imputed_count, quality_summary,
            computed_at
        )
        SELECT
            site_id,
            DATE_TRUNC('hour', timestamp)                      AS hour_start,
            AVG(consumption_kw_imputed)::FLOAT4                AS avg_consumption_kw,
            MAX(consumption_kw_imputed)::FLOAT4                AS max_consumption_kw,
            MIN(consumption_kw_imputed)::FLOAT4                AS min_consumption_kw,
            AVG(load_percent)::FLOAT4                          AS avg_load_percent,
            AVG(temperature_celsius)::FLOAT4                   AS avg_temperature_celsius,
            AVG(humidity_percent)::FLOAT4                      AS avg_humidity_percent,
            -- kWh = avg_kW × durée_réelle_en_heures
            -- chaque mesure représente 1 min → reading_count minutes = reading_count/60 h
            (AVG(consumption_kw_imputed) * COUNT(*) / 60.0)::FLOAT4              AS consommation_kwh,
            (AVG(consumption_kw_imputed) * COUNT(*) / 60.0 * :tarif)::FLOAT4     AS cout_eur,
            COUNT(*)::SMALLINT                                 AS reading_count,
            SUM(CASE WHEN is_imputed THEN 1 ELSE 0 END)::SMALLINT AS imputed_count,
            -- qualité dominante : critical/degraded > partial > good
            CASE
                WHEN SUM(CASE WHEN data_quality = 'critical'  THEN 1 ELSE 0 END) > 0 THEN 'degraded'
                WHEN SUM(CASE WHEN data_quality = 'degraded'  THEN 1 ELSE 0 END) > 0 THEN 'degraded'
                WHEN SUM(CASE WHEN data_quality = 'partial'   THEN 1 ELSE 0 END) > 0 THEN 'partial'
                ELSE 'good'
            END                                                AS quality_summary,
            NOW()                                              AS computed_at
        FROM silver.silver_readings
        WHERE DATE_TRUNC('hour', timestamp) = :hour_start
        GROUP BY site_id, DATE_TRUNC('hour', timestamp)
        ON CONFLICT (site_id, hour_start) DO UPDATE SET
            avg_consumption_kw      = EXCLUDED.avg_consumption_kw,
            max_consumption_kw      = EXCLUDED.max_consumption_kw,
            min_consumption_kw      = EXCLUDED.min_consumption_kw,
            avg_load_percent        = EXCLUDED.avg_load_percent,
            avg_temperature_celsius = EXCLUDED.avg_temperature_celsius,
            avg_humidity_percent    = EXCLUDED.avg_humidity_percent,
            consommation_kwh        = EXCLUDED.consommation_kwh,
            cout_eur                = EXCLUDED.cout_eur,
            reading_count           = EXCLUDED.reading_count,
            imputed_count           = EXCLUDED.imputed_count,
            quality_summary         = EXCLUDED.quality_summary,
            computed_at             = EXCLUDED.computed_at
    """)
    with get_engine().begin() as conn:
        result = conn.execute(sql, {"hour_start": hour_start, "tarif": tarif})
    return result.rowcount


def _upsert_alerts_from_silver() -> int:
    """Génère des alertes Gold depuis les dépassements de seuil en Silver."""
    sql = text("""
        INSERT INTO gold.gold_alerts (
            alert_id, site_id, alert_timestamp,
            source, debut, fin,
            severity, alert_type, message,
            value, threshold, is_active
        )
        SELECT
            'ALR-' || site_id || '-' || EXTRACT(EPOCH FROM timestamp)::BIGINT AS alert_id,
            site_id,
            timestamp                                                           AS alert_timestamp,
            'silver'                                                            AS source,
            timestamp                                                           AS debut,
            NULL::TIMESTAMPTZ                                                   AS fin,
            CASE
                WHEN load_percent >= :critical_threshold THEN 'critical'
                ELSE 'high'
            END                                                                 AS severity,
            'threshold'                                                         AS alert_type,
            'Dépassement de seuil : ' || ROUND(load_percent::NUMERIC, 1) || '%%' AS message,
            consumption_kw_imputed::FLOAT4                                      AS value,
            CASE
                WHEN load_percent >= :critical_threshold
                    THEN (capacity_kw * :critical_threshold / 100.0)::FLOAT4
                    ELSE (capacity_kw * :high_threshold    / 100.0)::FLOAT4
            END                                                                 AS threshold,
            TRUE                                                                AS is_active
        FROM (
            SELECT s.*, (b.payload -> '_site' ->> 'capacity_kw')::int AS capacity_kw
            FROM silver.silver_readings s
            JOIN bronze.raw_readings b ON b.id = s.bronze_id
            WHERE s.load_percent >= :high_threshold
              AND s.timestamp > NOW() - INTERVAL '5 minutes'
        ) recent
        ON CONFLICT (alert_id) DO NOTHING
    """)
    with get_engine().begin() as conn:
        result = conn.execute(
            sql,
            {
                "high_threshold": ALERT_THRESHOLD_HIGH,
                "critical_threshold": ALERT_THRESHOLD_CRITICAL,
            },
        )
    return result.rowcount


def _upsert_alerts_from_api() -> int:
    """Importe les alertes remontées directement par l'API Mock."""
    raw_alerts = get_alerts()
    if not raw_alerts:
        return 0

    sql = text("""
        INSERT INTO gold.gold_alerts (
            alert_id, site_id, alert_timestamp,
            source, debut, fin,
            severity, alert_type, message,
            value, threshold, is_active
        ) VALUES (
            :alert_id, :site_id, :alert_timestamp,
            :source, :debut, :fin,
            :severity, :alert_type, :message,
            :value, :threshold, :is_active
        )
        ON CONFLICT (alert_id) DO NOTHING
    """)

    rows = []
    for a in raw_alerts:
        try:
            ts_raw = a.get("timestamp") or a.get("alert_timestamp")
            ts = datetime.fromisoformat(str(ts_raw))
        except (ValueError, TypeError):
            ts = datetime.now(tz=timezone.utc)

        # debut/fin depuis l'API si disponibles, sinon dérivés du timestamp
        try:
            debut_raw = a.get("start_time") or a.get("debut")
            debut = (
                datetime.fromisoformat(str(debut_raw))
                if debut_raw
                else ts
            )
        except (ValueError, TypeError):
            debut = ts

        try:
            fin_raw = a.get("end_time") or a.get("fin")
            fin = (
                datetime.fromisoformat(str(fin_raw))
                if fin_raw
                else None
            )
        except (ValueError, TypeError):
            fin = None

        rows.append(
            {
                "alert_id": a.get("id") or a.get("alert_id", f"API-{ts.timestamp()}"),
                "site_id": a.get("site_id"),
                "alert_timestamp": ts,
                "source": "api",
                "debut": debut,
                "fin": fin,
                "severity": a.get("severity", "low"),
                "alert_type": a.get("type") or a.get("alert_type", "anomaly"),
                "message": a.get("message"),
                "value": a.get("value"),
                "threshold": a.get("threshold"),
                "is_active": a.get("is_active", True),
            }
        )

    if not rows:
        return 0

    with get_engine().begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def _upsert_etat_capteur() -> int:
    """UPSERT gold.etat_capteur en croisant Silver (qualité mesurée) et l'API sensors/status.

    Convention capteur : {site_id}-MAIN — un capteur principal par site.

    Priorité des sources :
      1. L'API Mock (/api/v1/sensors/status) fournit le statut réel et la date
         de rétablissement prévue (failing_until). C'est la source de vérité.
      2. Silver (data_quality) sert de fallback si l'API est inaccessible,
         et permet de détecter les sites qui ont cessé d'émettre (en_panne).

    Mapping statut :
      API failing  → en_panne  (avec failing_until réel)
      Silver critical           → en_panne  (failing_until = NULL)
      Silver partial | degraded → degrade
      Silver good               → ok
    """
    # ── 1. Récupérer les statuts depuis l'API ────────────────────────────────
    api_statuses: dict[str, Any] = get_sensor_status()

    # ── 2. Calculer le statut depuis Silver (fallback + détection silencieux) ─
    sql_silver = text("""
        SELECT DISTINCT ON (s.site_id)
            s.site_id,
            CASE
                WHEN s.data_quality = 'critical'               THEN 'en_panne'
                WHEN s.data_quality IN ('partial', 'degraded') THEN 'degrade'
                ELSE 'ok'
            END AS statut_silver
        FROM silver.silver_readings s
        ORDER BY s.site_id, s.timestamp DESC
    """)

    sql_upsert = text("""
        INSERT INTO gold.etat_capteur (capteur, site_id, statut, en_panne_jusqu_a, mis_a_jour_le)
        VALUES (:capteur, :site_id, :statut, :en_panne_jusqu_a, NOW())
        ON CONFLICT (capteur, site_id) DO UPDATE SET
            statut           = EXCLUDED.statut,
            en_panne_jusqu_a = CASE
                                   WHEN EXCLUDED.statut = 'en_panne'
                                       THEN COALESCE(EXCLUDED.en_panne_jusqu_a, gold.etat_capteur.en_panne_jusqu_a)
                                   ELSE NULL
                               END,
            mis_a_jour_le    = EXCLUDED.mis_a_jour_le
    """)

    rows = []
    with get_engine().begin() as conn:
        silver_rows = {r.site_id: r.statut_silver for r in conn.execute(sql_silver)}

        # Construire les lignes à upsert : API en priorité, Silver en fallback
        all_site_ids = set(silver_rows) | set(api_statuses)
        for site_id in all_site_ids:
            capteur = f"{site_id}-MAIN"

            # Données API (si disponibles pour ce site)
            api_site = api_statuses.get(site_id) or {}
            # L'API peut renvoyer la structure directement sous site_id,
            # ou bien une liste de capteurs — on normalise les deux cas.
            if isinstance(api_site, list):
                # Plusieurs capteurs : on prend le premier en panne, sinon ok
                failing = next(
                    (c for c in api_site if c.get("status") == "failing"), None
                )
                api_site = failing or (api_site[0] if api_site else {})

            api_status = api_site.get("status")  # "ok" | "failing" | None
            failing_until = None
            if api_site.get("failing_until"):
                try:
                    failing_until = datetime.fromisoformat(
                        str(api_site["failing_until"])
                    )
                except (ValueError, TypeError):
                    failing_until = None

            # Résolution finale du statut
            if api_status == "failing":
                statut = "en_panne"
            elif api_status == "ok":
                statut = "ok"
            else:
                # Fallback Silver
                statut = silver_rows.get(site_id, "ok")

            rows.append(
                {
                    "capteur": capteur,
                    "site_id": site_id,
                    "statut": statut,
                    "en_panne_jusqu_a": failing_until,
                }
            )

        if rows:
            conn.execute(sql_upsert, rows)

    return len(rows)


# Règles de recommandation : (alert_type, severity) → (regle, titre, description)
_REGLES_RECOMMANDATION: dict[tuple[str, str], tuple[str, str, str]] = {
    ("threshold", "high"): (
        "threshold_high",
        "Réduire la charge",
        (
            "La consommation dépasse 90 % de la capacité. Vérifier les équipements non essentiels "
            "et envisager un délestage partiel."
        ),
    ),
    ("threshold", "critical"): (
        "threshold_critical",
        "Délestage d'urgence requis",
        (
            "Surcharge détectée (> 110 %). Interrompre immédiatement les équipements non critiques "
            "pour éviter un déclenchement disjoncteur."
        ),
    ),
    ("spike", "high"): (
        "spike_detected",
        "Analyser le pic de consommation",
        (
            "Un pic anormal a été détecté. Identifier l'équipement déclencheur et vérifier "
            "son état de fonctionnement."
        ),
    ),
    ("spike", "critical"): (
        "spike_critical",
        "Pic critique — intervention immédiate",
        (
            "Pic de consommation critique. Couper les charges non essentielles et alerter "
            "le responsable de site."
        ),
    ),
    ("anomaly", "low"): (
        "anomaly_low",
        "Surveiller l'anomalie",
        (
            "Une anomalie de faible sévérité a été détectée. Aucune action immédiate requise, "
            "surveiller l'évolution sur les prochaines heures."
        ),
    ),
    ("anomaly", "medium"): (
        "anomaly_medium",
        "Diagnostic recommandé",
        (
            "Anomalie de consommation détectée. Lancer un diagnostic des capteurs et vérifier "
            "la cohérence des mesures."
        ),
    ),
    ("outage", "high"): (
        "outage_detected",
        "Coupure détectée — intervention maintenance",
        (
            "Une coupure d'alimentation a été enregistrée. Contacter la maintenance et vérifier "
            "les protections électriques."
        ),
    ),
    ("sensor", "medium"): (
        "sensor_issue",
        "Vérification capteur",
        (
            "Des données capteur manquantes ou incohérentes ont été détectées. Vérifier "
            "la connectivité et l'alimentation du capteur."
        ),
    ),
}


def _insert_recommandations_for_new_alerts() -> int:
    """Génère une recommandation pour chaque alerte active sans recommandation existante."""
    # Récupérer les alertes actives sans recommandation
    sql_select = text("""
        SELECT a.alert_id, a.alert_type, a.severity
        FROM gold.gold_alerts a
        WHERE a.is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM gold.recommandation r WHERE r.alert_id = a.alert_id
          )
        ORDER BY a.created_at DESC
        LIMIT 100
    """)
    sql_insert = text("""
        INSERT INTO gold.recommandation (alert_id, regle, titre, description)
        VALUES (:alert_id, :regle, :titre, :description)
    """)

    rows = []
    with get_engine().begin() as conn:
        alerts = conn.execute(sql_select).fetchall()
        for row in alerts:
            key = (row.alert_type, row.severity)
            # Cherche la règle exacte, puis par type seul, sinon règle générique
            regle_info = _REGLES_RECOMMANDATION.get(key) or next(
                (
                    v
                    for (t, _), v in _REGLES_RECOMMANDATION.items()
                    if t == row.alert_type
                ),
                (
                    "alerte_generique",
                    "Vérification requise",
                    "Une alerte a été déclenchée sur ce site. Examiner les mesures récentes.",
                ),
            )
            rows.append(
                {
                    "alert_id": row.alert_id,
                    "regle": regle_info[0],
                    "titre": regle_info[1],
                    "description": regle_info[2],
                }
            )
        if rows:
            conn.execute(sql_insert, rows)
    return len(rows)


def run(now: datetime | None = None) -> dict[str, int]:
    """Point d'entrée.

    - Toujours : UPSERT gold_latest + etat_capteur + alertes + recommandations
    - Si minute == 0 : INSERT gold_hourly pour l'heure écoulée
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    logger.info("[AGGREGATE] Démarrage (%s)", now.strftime("%H:%M UTC"))

    nb_latest = _upsert_gold_latest()
    nb_etat_capteur = _upsert_etat_capteur()
    nb_alerts_silver = _upsert_alerts_from_silver()
    nb_alerts_api = _upsert_alerts_from_api()
    nb_recommandations = _insert_recommandations_for_new_alerts()

    nb_hourly = 0
    if now.minute == 0:
        # Agrège l'heure qui vient de se terminer
        from datetime import timedelta

        prev_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        nb_hourly = _insert_hourly(prev_hour)
        logger.info(
            "[AGGREGATE] Horaire %s : %d site(s)",
            prev_hour.strftime("%H:00"),
            nb_hourly,
        )

    logger.info(
        "[AGGREGATE] gold_latest=%d, etat_capteur=%d, gold_hourly=%d, "
        "alerts(seuil)=%d, alerts(api)=%d, recommandations=%d",
        nb_latest,
        nb_etat_capteur,
        nb_hourly,
        nb_alerts_silver,
        nb_alerts_api,
        nb_recommandations,
    )
    return {
        "gold_latest": nb_latest,
        "etat_capteur": nb_etat_capteur,
        "gold_hourly": nb_hourly,
        "alerts_silver": nb_alerts_silver,
        "alerts_api": nb_alerts_api,
        "recommandations": nb_recommandations,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run()