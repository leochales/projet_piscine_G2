-- =============================================================================
-- EnerVision : métriques métier pour Grafana (SMARTOPS-105)
-- 19 : une vue d'agrégats, lue par postgres-exporter avec le compte monitoring.
--
-- Le compte monitoring n'a que pg_monitor (06_roles.sql) : il ne lit aucune
-- mesure. Cette vue ne lui montre que des totaux et des horodatages. Elle
-- s'exécute avec les droits de son propriétaire, pas avec ceux de monitoring.
--
-- Rejouable (db/tools/migrate.sh) : CREATE OR REPLACE et GRANT.
--
-- Dernière collecte : une lecture d'index par site, comme gold.etat_site.
-- Les comptages parcourent encore les tables ; postgres-exporter ne relance
-- la vue que toutes les 60 s (cache_seconds de queries.yaml).
-- =============================================================================

BEGIN;

CREATE OR REPLACE VIEW gold.supervision_metier AS
WITH derniere_prevision AS (
    SELECT DISTINCT ON (id_site, heure_prevue)
        id_site,
        heure_prevue,
        consommation_prevue_kwh
    FROM gold.prediction
    WHERE heure_prevue < date_trunc('hour', now())
    ORDER BY id_site ASC, heure_prevue ASC, calculee_le DESC
),

-- ingested_at de la mesure la plus récente de chaque site actif.
-- L'index (id_site, horodatage) suffit : pas de parcours de bronze.
derniere_collecte AS (
    SELECT max(b.ingested_at) AS ingested_at
    FROM app.site AS s
    CROSS JOIN
        LATERAL (
            SELECT br.ingested_at
            FROM bronze.raw_readings AS br
            WHERE br.id_site = s.id_site
            ORDER BY br.horodatage DESC
            LIMIT 1
        ) AS b
    WHERE s.statut = 'active'
)

SELECT
    (SELECT count(*) FROM bronze.raw_readings)::double precision
        AS mesures_collectees,
    extract(EPOCH FROM (SELECT ingested_at FROM derniere_collecte))
        AS derniere_collecte_epoch,
    (
        SELECT count(*)
        FROM silver.silver_readings
        WHERE imputation_method = 'linear_interpolation'
    )::double precision AS valeurs_imputees,
    (
        SELECT coalesce(sum(consommation_kw), 0) FROM gold.derniere_mesure
    )::double precision AS puissance_kw,
    (SELECT count(*) FROM gold.prediction)::double precision
        AS previsions_ecrites,
    extract(EPOCH FROM (SELECT max(calculee_le) FROM gold.prediction))
        AS dernier_calcul_epoch,
    (
        SELECT count(*) FROM gold.alerte
        WHERE fin IS null
    )::double precision AS alertes_en_cours,
    (
        SELECT
            CASE
                WHEN sum(c.consommation_kwh) > 0
                    THEN (
                        100 * sum(
                            abs(
                                p.consommation_prevue_kwh
                                - c.consommation_kwh
                            )
                        ) / sum(c.consommation_kwh)
                    )::double precision
            END
        FROM derniere_prevision AS p
        INNER JOIN gold.consommation_horaire AS c
            ON p.id_site = c.id_site AND p.heure_prevue = c.heure
        WHERE
            c.consommation_kwh IS NOT null
            AND c.heure_complete
    ) AS ecart_prevu_reel_pct;

COMMENT ON VIEW gold.supervision_metier IS
'Totaux pour Grafana : mesures collectées, imputation, puissance instantanée, '
'prévisions, alertes en cours, et écart entre le prévu et le réel sur les '
'heures complètes déjà passées. Pas le WAPE d''entraînement (il reste dans '
'MLflow).';

-- USAGE du schéma, sans droit de lecture sur les tables : monitoring ne
-- résout que la vue accordée juste après.
GRANT USAGE ON SCHEMA gold TO monitoring;
GRANT SELECT ON gold.supervision_metier TO monitoring;

COMMIT;
