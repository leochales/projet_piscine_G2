-- =============================================================================
-- EnerVision : dernière mesure et état des sites dans gold (SMARTOPS-23)
-- 13 : mise à jour de gold.derniere_mesure depuis silver, et vue de l'état
--      de chaque site (transmission, capteurs) pour le bandeau du dashboard.
--
-- gold.etat_capteur est rempli par l'ETL depuis GET /api/v1/sensors/status
-- (etl/gold_latest.py). Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

COMMENT ON COLUMN gold.derniere_mesure.horodatage IS
'Minute de la dernière mesure transmise par le site (UTC), hors perte réseau';
COMMENT ON COLUMN gold.derniere_mesure.consommation_kw IS
'Valeur mesurée, jamais imputée ; NULL si capteur en panne ou hors plage';

-- -----------------------------------------------------------------------------
-- Dernière mesure, appelée chaque minute par l'ETL (etl/gold_latest.py)
--
-- Par site actif, prend la dernière minute de silver qui vient d'une mesure
-- transmise par le site. Sont ignorées :
--   - les minutes sans mesure en bronze (bronze_id NULL : trou de collecte) ;
--   - les mesures « perte réseau » : pendant une perte réseau, l'API Mock
--     répond quand même, avec toutes les valeurs à null et la raison
--     network_loss. Le site n'a rien transmis ;
--   - les mesures d'amorçage (etl/bootstrap.py, payload bronze marqué
--     "_source": "readings_amorcage") : historique simulé par /readings, pas
--     une mesure transmise par le site. Sans cela, sur une base neuve, la
--     dernière mesure serait une valeur simulée jusqu'au premier /current.
-- La ligne garde alors la dernière mesure connue, et son horodatage vieillit,
-- ce que la vue gold.etat_site signale. Une mesure refusée par la validation
-- (rejected_reading) compte comme transmise : le site répond, mal.
-- La recherche s'arrête à la mesure déjà en gold (parcours de la clé primaire
-- de silver depuis la fin) : le coût ne dépend pas de la taille de silver.
--
-- Exécutée avec les droits de l'appelant (compte etl).
-- Retourne le nombre de sites mis à jour.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.mettre_a_jour_derniere_mesure()
RETURNS INTEGER
-- plpgsql, comme gold.calculer_consommation_horaire() (12_gold_horaire.sql)
LANGUAGE plpgsql
AS $$
DECLARE
    nb INTEGER;
BEGIN
    INSERT INTO gold.derniere_mesure AS d (
        id_site, horodatage, consommation_kw, facteur_puissance,
        temperature_c, data_quality, null_reasons
    )
    SELECT
        s.id_site,
        r.horodatage,
        r.consumption_kw_raw,
        r.power_factor,
        r.temperature_celsius,
        r.data_quality,
        r.null_reasons
    FROM app.site AS s
    LEFT JOIN gold.derniere_mesure AS g ON s.id_site = g.id_site
    CROSS JOIN LATERAL (
        SELECT
            sr.horodatage,
            sr.consumption_kw_raw,
            sr.power_factor,
            sr.temperature_celsius,
            sr.data_quality,
            sr.null_reasons
        FROM silver.silver_readings AS sr
        WHERE
            sr.id_site = s.id_site
            AND sr.bronze_id IS NOT null
            AND NOT 'network_loss' = any(sr.null_reasons)
            AND sr.horodatage > coalesce(g.horodatage, '-infinity')
            -- Lecture de la ligne bronze par sa clé primaire
            AND NOT EXISTS (
                SELECT 1 FROM bronze.raw_readings AS br
                WHERE
                    br.id = sr.bronze_id
                    AND br.payload ->> '_source' = 'readings_amorcage'
            )
        ORDER BY sr.horodatage DESC
        LIMIT 1
    ) AS r
    WHERE s.statut = 'active'
    ON CONFLICT ON CONSTRAINT derniere_mesure_pkey DO UPDATE SET
        horodatage = excluded.horodatage,
        consommation_kw = excluded.consommation_kw,
        facteur_puissance = excluded.facteur_puissance,
        temperature_c = excluded.temperature_c,
        data_quality = excluded.data_quality,
        null_reasons = excluded.null_reasons
    -- Jamais de retour en arrière, même si silver est retraité
    WHERE excluded.horodatage > d.horodatage;

    GET DIAGNOSTICS nb = ROW_COUNT;
    RETURN nb;
END;
$$;

REVOKE ALL ON FUNCTION gold.mettre_a_jour_derniere_mesure() FROM public;
GRANT EXECUTE ON FUNCTION gold.mettre_a_jour_derniere_mesure() TO etl;

-- -----------------------------------------------------------------------------
-- État de chaque site actif, lu par l'API (bandeau « sites qui ne transmettent
-- plus » et état des capteurs). Une vue et non une table : « ne transmet plus »
-- dépend de l'heure de lecture.
--   - collecte_a_jour : l'ETL a reçu une mesure de l'API Mock, pour au
--     moins un site, depuis moins de 5 minutes (les mesures « perte réseau »
--     comptent : l'API a répondu). Faux si la panne est de notre côté : ETL
--     arrêté, API Mock injoignable ;
--   - transmet : une mesure transmise par le site depuis moins de 5 minutes
--     (la collecte tourne chaque minute ; la marge absorbe un passage de l'ETL
--     en retard). Un site qui n'a jamais transmis est à false. NULL (inconnu)
--     quand la collecte n'est pas à jour : le bandeau « ne transmet plus » ne
--     doit pas accuser les sites d'une panne de la collecte ;
--   - etat_capteurs : critical si le capteur réseau est en panne (aucune
--     donnée), degraded si un autre capteur l'est, ok sinon ; NULL tant que
--     l'état des capteurs n'a jamais été lu. Même règle que le champ overall
--     de l'API Mock.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.etat_site AS
WITH collecte AS (
    -- Dernière mesure reçue en bronze, tous sites actifs confondus. Une
    -- recherche par site sur la clé unique (id_site, horodatage) de bronze :
    -- le coût ne dépend pas de la taille de bronze.
    SELECT max(b.horodatage) AS derniere_collecte_le
    FROM app.site AS s
    CROSS JOIN
        LATERAL (
            SELECT br.horodatage
            FROM bronze.raw_readings AS br
            WHERE br.id_site = s.id_site
            ORDER BY br.horodatage DESC
            LIMIT 1
        ) AS b
    WHERE s.statut = 'active'
),

c AS (
    SELECT
        ec.id_site,
        count(*) AS nb_capteurs,
        coalesce(
            array_agg(ec.capteur ORDER BY ec.capteur)
            FILTER (WHERE ec.statut = 'failing'),
            '{}'
        ) AS capteurs_en_panne,
        -- Dernier rétablissement annoncé parmi les capteurs en panne
        max(ec.en_panne_jusqu_a) FILTER (
            WHERE ec.statut = 'failing'
        ) AS retablissement_prevu,
        max(ec.mis_a_jour_le) AS capteurs_mis_a_jour_le
    FROM gold.etat_capteur AS ec
    GROUP BY ec.id_site
)

-- Une fois la vue déployée, toute nouvelle colonne s'ajoute à la fin :
-- CREATE OR REPLACE VIEW (rejoué par la migration) refuse de réordonner ou de
-- renommer les colonnes existantes
SELECT
    s.id_site,
    d.horodatage AS derniere_mesure_le,
    k.derniere_collecte_le,
    c.retablissement_prevu,
    c.capteurs_mis_a_jour_le,
    coalesce(
        k.derniere_collecte_le >= now() - INTERVAL '5 minutes', false
    ) AS collecte_a_jour,
    CASE
        WHEN NOT coalesce(
            k.derniere_collecte_le >= now() - INTERVAL '5 minutes', false
        ) THEN null
        ELSE coalesce(d.horodatage >= now() - INTERVAL '5 minutes', false)
    END AS transmet,
    CASE
        WHEN c.nb_capteurs IS null THEN null
        WHEN 'network' = any(c.capteurs_en_panne) THEN 'critical'
        WHEN cardinality(c.capteurs_en_panne) > 0 THEN 'degraded'
        ELSE 'ok'
    END AS etat_capteurs,
    coalesce(c.capteurs_en_panne, '{}') AS capteurs_en_panne
FROM app.site AS s
CROSS JOIN collecte AS k
LEFT JOIN gold.derniere_mesure AS d ON s.id_site = d.id_site
LEFT JOIN c ON s.id_site = c.id_site
WHERE s.statut = 'active';

-- L'API lit gold : ses droits par défaut couvrent les tables créées par ce
-- compte, accordés ici explicitement comme pour les autres objets ajoutés
GRANT SELECT ON gold.etat_site TO api;

COMMIT;
