-- =============================================================================
-- EnerVision : métriques métier pour Grafana (SMARTOPS-105)
-- 19 : une vue d'agrégats, lue par postgres-exporter avec le compte monitoring.
--
-- Le compte monitoring n'a que pg_monitor (06_roles.sql) : il ne lit aucune
-- mesure. Cette vue ne lui montre que des totaux et des horodatages. Elle
-- s'exécute avec les droits de son propriétaire, pas avec ceux de monitoring.
--
-- Ce qui grossit avec l'historique est borné à 24 h (collecte, imputation,
-- écart prévu/réel) : une dérive récente reste visible, et la lecture ne
-- trie plus toutes les prévisions ni ne compte bronze et silver en entier.
-- La puissance ne garde que les sites actifs dont la mesure a moins de
-- 5 minutes, comme « transmet » dans gold.etat_site. Le nombre de
-- prévisions et la date du dernier calcul restent globaux : gold.prediction
-- est horaire, et le tableau veut ce stock. postgres-exporter met le
-- résultat en cache 60 s (cache_seconds de queries.yaml).
--
-- Rejouable (db/tools/migrate.sh) : CREATE OR REPLACE, index IF NOT EXISTS,
-- GRANT.
-- =============================================================================

BEGIN;

-- Dernière ingestion et volume des 24 h : une lecture d'index par site actif.
-- ingested_at, pas horodatage : un rattrapage de minutes anciennes a une
-- vieille minute de mesure, mais une date d'enregistrement récente.
CREATE INDEX IF NOT EXISTS idx_raw_readings_site_ingested
ON bronze.raw_readings (id_site, ingested_at DESC);

CREATE OR REPLACE VIEW gold.supervision_metier AS
WITH bornes AS (
    SELECT
        date_trunc('hour', now()) AS heure_courante,
        date_trunc('hour', now()) - interval '24 hours' AS depuis
),

-- Dernière prévision de chaque heure déjà écoulée, sur 24 h seulement.
derniere_prevision AS (
    SELECT DISTINCT ON (p.id_site, p.heure_prevue)
        p.id_site,
        p.heure_prevue,
        p.consommation_prevue_kwh
    FROM gold.prediction AS p
    CROSS JOIN bornes AS b
    WHERE p.heure_prevue >= b.depuis AND p.heure_prevue < b.heure_courante
    ORDER BY p.id_site ASC, p.heure_prevue ASC, p.calculee_le DESC
),

derniere_collecte AS (
    SELECT max(b.ingested_at) AS ingested_at
    FROM app.site AS s
    CROSS JOIN
        LATERAL (
            SELECT br.ingested_at
            FROM bronze.raw_readings AS br
            WHERE br.id_site = s.id_site
            ORDER BY br.ingested_at DESC
            LIMIT 1
        ) AS b
    WHERE s.statut = 'active'
),

mesures_recentes AS (
    SELECT coalesce(sum(n.nb), 0) AS nb
    FROM app.site AS s
    CROSS JOIN
        LATERAL (
            SELECT count(*) AS nb
            FROM bronze.raw_readings AS br
            WHERE
                br.id_site = s.id_site
                AND br.ingested_at >= now() - interval '24 hours'
        ) AS n
    WHERE s.statut = 'active'
)

SELECT
    (SELECT nb FROM mesures_recentes)::double precision AS mesures_collectees,
    extract(EPOCH FROM (SELECT ingested_at FROM derniere_collecte))
        AS derniere_collecte_epoch,
    -- Taux, pas le stock depuis le début : heures complètes des dernières
    -- 24 h dans gold (une ligne par heure), pas un parcours de silver.
    (
        SELECT
            CASE
                WHEN sum(h.nb_mesures) > 0
                    THEN (
                        100 * sum(h.nb_imputees)::numeric / sum(h.nb_mesures)
                    )::double precision
            END
        FROM gold.consommation_horaire AS h
        INNER JOIN app.site AS s ON h.id_site = s.id_site
        CROSS JOIN bornes AS b
        WHERE
            s.statut = 'active'
            AND h.heure_complete
            AND h.heure >= b.depuis
            AND h.heure < b.heure_courante
    ) AS valeurs_imputees,
    (
        SELECT coalesce(sum(d.consommation_kw), 0)
        FROM gold.derniere_mesure AS d
        INNER JOIN app.site AS s ON d.id_site = s.id_site
        WHERE
            s.statut = 'active'
            AND d.horodatage >= now() - interval '5 minutes'
    )::double precision AS puissance_kw,
    (SELECT count(*) FROM gold.prediction)::double precision
        AS previsions_ecrites,
    extract(EPOCH FROM (SELECT max(calculee_le) FROM gold.prediction))
        AS dernier_calcul_epoch,
    (
        SELECT count(*)
        FROM gold.alerte AS a
        INNER JOIN app.site AS s ON a.id_site = s.id_site
        WHERE a.fin IS null AND s.statut = 'active'
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
'Totaux pour Grafana. Collecte, imputation et écart prévu/réel : 24 h. '
'Puissance : sites actifs avec une mesure de moins de 5 minutes. '
'Alertes en cours : sites actifs. Pas le WAPE d''entraînement (MLflow).';

-- USAGE du schéma, sans droit de lecture sur les tables : monitoring ne
-- résout que la vue accordée juste après.
GRANT USAGE ON SCHEMA gold TO monitoring;
GRANT SELECT ON gold.supervision_metier TO monitoring;

COMMIT;
