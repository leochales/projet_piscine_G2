-- =============================================================================
-- EnerVision : alertes de l'ETL dans gold (SMARTOPS-26)
-- 16 : seuil d'alerte par site, et détection des alertes depuis silver :
--      dépassements de seuil et pannes des capteurs électriques.
--
-- Les alertes de l'API Mock (GET /api/v1/alerts) ne sont pas reprises : l'API
-- les tire au hasard à chaque appel et leur alert_id contient l'heure de
-- l'appel (voir etl/api_client.py). Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Seuil d'alerte de chaque site, en % de sa capacité (US3)
--
-- Valeurs initiales tirées de 7 jours de mesures (octobre 2026), avec la
-- règle des 3 mesures consécutives : 90 % donnerait 25 alertes par jour au
-- datacenter (qui tourne à 93 % en temps normal) et 10 à 15 aux usines.
--   - datacenter : 100 % → 0,7 alerte par jour ;
--   - usine      :  98 % → 0,1 à 0,6 alerte par jour ;
--   - autres     :  90 % → 0,3 alerte par jour au plus.
-- Appliquées à l'ajout de la colonne, puis à chaque nouveau site créé sans
-- seuil (trg_site_seuil_alerte) : un seuil modifié ensuite n'est jamais
-- écrasé par une migration.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.seuil_alerte_par_defaut(type_site VARCHAR)
RETURNS NUMERIC
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE type_site
        WHEN 'datacenter' THEN 100
        WHEN 'factory' THEN 98
        ELSE 90
    END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'site'
          AND column_name = 'seuil_alerte_pct'
    ) THEN
        ALTER TABLE app.site
        ADD COLUMN seuil_alerte_pct NUMERIC(5, 1) NOT NULL DEFAULT 90
        CHECK (seuil_alerte_pct > 0);

        UPDATE app.site
        SET seuil_alerte_pct = app.seuil_alerte_par_defaut(type);
    END IF;
END
$$;

-- Plus de DEFAULT fixe : un site créé sans seuil le reçoit selon son type.
-- Le déclencheur passe avant la vérification du NOT NULL.
ALTER TABLE app.site
ALTER COLUMN seuil_alerte_pct DROP DEFAULT;

-- Seuil posé par le déclencheur :
--   - seuil vide (création ou modification) : celui du type ;
--   - type corrigé (office → datacenter) : le seuil suit le nouveau type,
--     sauf s'il avait été réglé à la main (différent de celui de l'ancien
--     type) ou s'il est modifié dans la même requête.
CREATE OR REPLACE FUNCTION app.poser_seuil_alerte()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.seuil_alerte_pct IS null
        OR (
            TG_OP = 'UPDATE'
            AND NEW.type IS DISTINCT FROM OLD.type
            AND NEW.seuil_alerte_pct = OLD.seuil_alerte_pct
            AND OLD.seuil_alerte_pct = app.seuil_alerte_par_defaut(OLD.type)
        )
    THEN
        NEW.seuil_alerte_pct := app.seuil_alerte_par_defaut(NEW.type);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_site_seuil_alerte
BEFORE INSERT OR UPDATE OF type, seuil_alerte_pct ON app.site
FOR EACH ROW EXECUTE FUNCTION app.poser_seuil_alerte();

COMMENT ON COLUMN app.site.seuil_alerte_pct IS
'Seuil d''alerte en % de capacite_kw (alerte après 3 mesures au-dessus)';

-- Même lecture limitée de app.site que pour les autres colonnes (06_roles.sql)
GRANT SELECT (seuil_alerte_pct) ON app.site TO etl, model;

-- -----------------------------------------------------------------------------
-- Capteur en panne, pour les alertes de type sensor
-- -----------------------------------------------------------------------------
ALTER TABLE gold.alerte
ADD COLUMN IF NOT EXISTS capteur VARCHAR(20);

COMMENT ON COLUMN gold.alerte.capteur IS
'Capteur en panne (alertes sensor seulement) : consumption ou electrical';

-- Un capteur pour toute alerte sensor, et seulement pour elles.
-- alerte_capteur_check, la première version, acceptait une alerte sensor
-- sans capteur : elle est remplacée sur les bases déjà migrées.
ALTER TABLE gold.alerte
DROP CONSTRAINT IF EXISTS alerte_capteur_check;

-- ADD CONSTRAINT n'a pas de IF NOT EXISTS : on vérifie avant de l'ajouter
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'alerte_capteur_type_check'
          AND conrelid = 'gold.alerte'::regclass
    ) THEN
        ALTER TABLE gold.alerte
        ADD CONSTRAINT alerte_capteur_type_check CHECK (
            (type = 'sensor') = (capteur IS NOT null)
            AND (capteur IS null OR capteur IN ('consumption', 'electrical'))
        );
    END IF;
END
$$;

-- Une alerte de l'ETL par site, type, capteur et début : chaque passage met à
-- jour l'alerte en cours au lieu d'en créer une nouvelle
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerte_etl
ON gold.alerte (id_site, type, capteur, debut) NULLS NOT DISTINCT
WHERE source = 'etl';


-- -----------------------------------------------------------------------------
-- Détection, appelée chaque minute par l'ETL (etl/gold_alerts.py)
--
-- Trois suivis par site, avec la même règle :
--   - threshold : consommation mesurée (consumption_kw_raw, jamais une valeur
--     estimée) égale au seuil du site ou au-dessus. high, critical si le
--     maximum atteint vaut 110 % de la capacité ou plus ;
--   - sensor / consumption : raison consumption_sensor_failure. high : plus
--     de consommation, donc plus de détection des pics ;
--   - sensor / electrical : raison electrical_sensor_failure. medium : la
--     consommation reste mesurée.
-- Une alerte commence après 3 minutes en défaut consécutives (debut = la
-- première) et se termine après 3 minutes sans défaut consécutives (fin = la
-- première). Une minute sans information est ignorée, elle ne compte ni dans
-- un sens ni dans l'autre : consommation nulle pour un seuil, minute non
-- transmise (no_reading, network_loss) pour un capteur. Un site qui ne
-- transmet plus garde donc son alerte en cours. Mais plus de 5 minutes sans
-- information coupent la série : trois minutes hautes espacées d'une heure
-- n'ouvrent pas d'alerte.
-- Les pannes de capteur de l'API Mock durent presque toutes moins d'une
-- minute : sans la règle des 3 minutes, il y aurait 58 alertes par jour et
-- par capteur, contre 0,1.
-- C'est pourquoi la panne est lue dans silver (null_reasons), et non dans
-- gold.etat_capteur (SMARTOPS-23) : ce dernier donne l'état instantané de
-- l'API, sans la règle des 3 minutes. Un capteur peut donc y être en panne
-- sans qu'aucune alerte ne soit ouverte : c'est voulu.
--
-- Fenêtre : par site, les `fenetre` dernières minutes de silver seulement,
-- même pendant une alerte de plusieurs jours : le coût d'un passage ne
-- grandit pas avec la durée des alertes. Une alerte qui a commencé avant la
-- fenêtre et la recouvre est reprise de gold.alerte (début et maximum
-- atteint), puis prolongée ou fermée par les minutes de la fenêtre. Le temps
-- de référence est la dernière minute du site, et non now() : silver en
-- retard ne ferme rien à tort.
-- Une alerte en cours dont le début change (seuil modifié, minute réécrite)
-- garde sa ligne et son identifiant. Une alerte en cours que le calcul ne
-- retrouve plus (défaut disparu, site désactivé) est fermée à la dernière
-- minute de son site.
--
-- Exécutée avec les droits de l'appelant (compte etl).
-- Retourne les alertes créées ou modifiées.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.detecter_alertes(
    fenetre INTERVAL DEFAULT INTERVAL '3 hours'
)
RETURNS TABLE (
    id_site VARCHAR,
    type VARCHAR,  -- noqa: RF04
    capteur VARCHAR,
    debut TIMESTAMPTZ,
    en_cours BOOLEAN
)
-- plpgsql, comme gold.calculer_consommation_horaire() (12_gold_horaire.sql)
LANGUAGE plpgsql
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    WITH suivis AS (
        -- Un suivi = un site et ce qu'on y surveille
        SELECT
            s.id_site,
            s.capacite_kw,
            round(s.capacite_kw * s.seuil_alerte_pct / 100, 2) AS seuil,
            k.type,
            k.capteur,
            m.ref
        FROM app.site AS s
        CROSS JOIN (
            VALUES
            ('threshold'::VARCHAR, null::VARCHAR),
            ('sensor', 'consumption'),
            ('sensor', 'electrical')
        ) AS k (type, capteur)
        CROSS JOIN LATERAL (
            SELECT max(sr.horodatage) AS ref
            FROM silver.silver_readings AS sr
            WHERE sr.id_site = s.id_site
        ) AS m
        WHERE s.statut = 'active' AND m.ref IS NOT null
    ),

    depart AS (
        -- Début de la fenêtre, et alerte qui a commencé avant et la recouvre
        -- (amorce) : son état n'est pas recalculé, il est repris de la base
        SELECT
            u.*,
            u.ref - fenetre AS depuis,
            am.debut AS amorce_debut,
            am.valeur AS amorce_valeur
        FROM suivis AS u
        LEFT JOIN LATERAL (
            SELECT a.debut, a.valeur
            FROM gold.alerte AS a
            WHERE
                a.source = 'etl'
                AND a.id_site = u.id_site
                AND a.type = u.type
                AND a.capteur IS NOT DISTINCT FROM u.capteur
                AND a.debut < u.ref - fenetre
                AND (a.fin IS null OR a.fin > u.ref - fenetre)
            ORDER BY a.debut DESC
            LIMIT 1
        ) AS am ON true
    ),

    minutes AS (
        -- Une ligne par minute utile : en_defaut vrai ou faux, jamais inconnu
        SELECT
            d.id_site,
            d.type,
            d.capteur,
            d.capacite_kw,
            d.seuil,
            sr.horodatage,
            sr.consumption_kw_raw AS kw,
            CASE
                WHEN d.type = 'threshold'
                    THEN sr.consumption_kw_raw >= d.seuil
                ELSE d.capteur || '_sensor_failure' = ANY (sr.null_reasons)
            END AS en_defaut
        FROM depart AS d
        INNER JOIN silver.silver_readings AS sr
            ON d.id_site = sr.id_site AND sr.horodatage >= d.depuis
        WHERE
            CASE
                WHEN d.type = 'threshold'
                    THEN sr.consumption_kw_raw IS NOT null
                ELSE NOT sr.null_reasons && ARRAY['no_reading', 'network_loss']
            END
    ),

    troncons AS (
        -- Plus de 5 minutes sans information coupent la série : trois minutes
        -- espacées d'une heure ne sont pas « 3 minutes consécutives »
        SELECT
            *,
            count(*) FILTER (WHERE coupure) OVER (
                PARTITION BY id_site, type, capteur ORDER BY horodatage
            ) AS troncon
        FROM (
            SELECT
                *,
                horodatage - lag(horodatage) OVER (
                    PARTITION BY id_site, type, capteur ORDER BY horodatage
                ) > INTERVAL '5 minutes' AS coupure
            FROM minutes
        ) AS t
    ),

    series AS (
        -- Suites de minutes consécutives dans le même état (îlots), sans
        -- trou de plus de 5 minutes, avec leur maximum
        SELECT
            id_site,
            type,
            capteur,
            en_defaut,
            min(horodatage) AS debut,
            count(*) AS nb,
            max(kw) AS kw_max
        FROM (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY id_site, type, capteur, troncon
                    ORDER BY horodatage
                )
                - row_number() OVER (
                    PARTITION BY id_site, type, capteur, troncon, en_defaut
                    ORDER BY horodatage
                ) AS ilot
            FROM troncons
        ) AS x
        GROUP BY id_site, type, capteur, troncon, en_defaut, ilot

        UNION ALL

        -- L'amorce compte comme une suite en défaut, avant la fenêtre
        SELECT
            id_site,
            type,
            capteur,
            true,
            amorce_debut,
            3,
            amorce_valeur
        FROM depart
        WHERE amorce_debut IS NOT null
    ),

    franches AS (
        -- Seules les suites d'au moins 3 minutes changent l'état de l'alerte.
        -- Début d'alerte : une suite en défaut après une suite sans défaut
        -- (ou aucune).
        SELECT
            id_site,
            type,
            capteur,
            debut,
            en_defaut
            AND lag(en_defaut) OVER (
                PARTITION BY id_site, type, capteur ORDER BY debut
            ) IS DISTINCT FROM true AS est_debut
        FROM series
        WHERE nb >= 3
    ),

    episodes AS (
        -- Chaque suite, franche ou non, rattachée à l'alerte commencée avant
        -- elle (episode 0 : aucune)
        SELECT
            s.*,
            f.debut IS NOT null AS franche,
            coalesce(f.est_debut, false) AS est_debut,
            count(*) FILTER (WHERE f.est_debut) OVER (
                PARTITION BY s.id_site, s.type, s.capteur ORDER BY s.debut
            ) AS episode
        FROM series AS s
        LEFT JOIN franches AS f
            ON
                s.id_site = f.id_site
                AND s.type = f.type
                AND s.capteur IS NOT DISTINCT FROM f.capteur
                AND s.debut = f.debut
    ),

    bornes AS (
        -- Fin de l'alerte : la première suite franche sans défaut qui la suit
        SELECT
            *,
            min(debut) FILTER (WHERE franche AND NOT en_defaut) OVER (
                PARTITION BY id_site, type, capteur, episode
            ) AS fin
        FROM episodes
        WHERE episode > 0
    ),

    alertes AS (
        -- Maximum atteint : sur les suites entre le début et la fin
        SELECT
            id_site,
            type,
            capteur,
            min(debut) FILTER (WHERE est_debut) AS debut,
            min(fin) AS fin,
            max(kw_max) FILTER (WHERE fin IS null OR debut < fin) AS valeur
        FROM bornes
        GROUP BY id_site, type, capteur, episode
    ),

    detail AS (
        SELECT
            a.*,
            u.seuil,
            u.capacite_kw,
            -- Alerte déjà en base avec le même début
            (
                SELECT e.id_alerte
                FROM gold.alerte AS e
                WHERE
                    e.source = 'etl'
                    AND e.id_site = a.id_site
                    AND e.type = a.type
                    AND e.capteur IS NOT DISTINCT FROM a.capteur
                    AND e.debut = a.debut
            ) AS id_meme_debut
        FROM alertes AS a
        INNER JOIN suivis AS u
            ON
                a.id_site = u.id_site
                AND a.type = u.type
                AND a.capteur IS NOT DISTINCT FROM u.capteur
    ),

    decalees AS (
        -- Alerte en cours dont le début a changé (seuil modifié, minute de
        -- silver réécrite) : elle garde sa ligne, donc son identifiant, sa
        -- prise en compte et sa recommandation. Rattachée à l'alerte
        -- recalculée sans ligne qui la recouvre, la plus proche en début ;
        -- une alerte recalculée ne reprend qu'une ligne.
        SELECT DISTINCT ON (c.id_site, c.type, c.capteur, c.debut) c.*
        FROM (
            SELECT DISTINCT ON (x.id_alerte)
                x.id_alerte,
                d.id_site,
                d.type,
                d.capteur,
                d.debut,
                abs(extract(EPOCH FROM d.debut - x.debut)) AS ecart
            FROM detail AS d
            INNER JOIN gold.alerte AS x
                ON
                    x.source = 'etl'
                    AND d.id_site = x.id_site
                    AND d.type = x.type
                    AND d.capteur IS NOT DISTINCT FROM x.capteur
                    AND x.fin IS null
                    AND (d.fin IS null OR d.fin > x.debut)
            WHERE
                d.id_meme_debut IS null
                AND NOT EXISTS (
                    SELECT 1 FROM detail AS m
                    WHERE m.id_meme_debut = x.id_alerte
                )
            ORDER BY x.id_alerte, ecart
        ) AS c
        ORDER BY c.id_site, c.type, c.capteur, c.debut, c.ecart
    ),

    cibles AS (
        -- Ligne à mettre à jour (vide : alerte nouvelle) et valeurs à écrire
        SELECT
            d.id_site,
            d.type,
            d.capteur,
            d.debut,
            d.fin,
            coalesce(d.id_meme_debut, c.id_alerte) AS id_cible,
            CASE
                WHEN d.capteur = 'electrical' THEN 'medium'
                WHEN d.type = 'threshold' AND d.valeur >= d.capacite_kw * 1.1
                    THEN 'critical'
                ELSE 'high'
            END AS severite,
            -- Pas de message pour un dépassement : le dashboard affiche
            -- lui-même la valeur et le seuil, au format français
            CASE
                WHEN d.capteur = 'consumption'
                    THEN 'Capteur de consommation en panne'
                WHEN d.capteur = 'electrical'
                    THEN 'Capteur électrique en panne'
            END AS message,
            -- Valeur et seuil n'ont de sens que pour un dépassement
            CASE WHEN d.type = 'threshold' THEN d.valeur END AS valeur,
            CASE WHEN d.type = 'threshold' THEN d.seuil END AS seuil
        FROM detail AS d
        LEFT JOIN decalees AS c
            ON
                d.id_site = c.id_site
                AND d.type = c.type
                AND d.capteur IS NOT DISTINCT FROM c.capteur
                AND d.debut = c.debut
    ),

    modifiees AS (
        UPDATE gold.alerte AS a
        SET
            debut = c.debut,
            fin = c.fin,
            severite = c.severite,
            message = c.message,
            valeur = c.valeur,
            seuil = c.seuil
        FROM cibles AS c
        WHERE
            a.id_alerte = c.id_cible
            -- Une alerte inchangée n'est pas réécrite (ni comptée)
            AND (a.debut, a.fin, a.severite, a.message, a.valeur, a.seuil)
            IS DISTINCT FROM
            (c.debut, c.fin, c.severite, c.message, c.valeur, c.seuil)
        RETURNING a.id_site, a.type, a.capteur, a.debut, a.fin IS null
    ),

    nouvelles AS (
        INSERT INTO gold.alerte AS a (
            id_site, source, type, capteur, severite, message,
            debut, fin, valeur, seuil
        )
        SELECT
            c.id_site,
            'etl',
            c.type,
            c.capteur,
            c.severite,
            c.message,
            c.debut,
            c.fin,
            c.valeur,
            c.seuil
        FROM cibles AS c
        WHERE c.id_cible IS null
        -- Deux passages en même temps : le second n'écrit rien
        ON CONFLICT (id_site, type, capteur, debut) WHERE source = 'etl'
        DO NOTHING
        RETURNING a.id_site, a.type, a.capteur, a.debut, a.fin IS null
    ),

    fermees AS (
        -- Alertes en cours que le calcul ne retrouve plus : défaut disparu
        -- (seuil relevé), site qui n'est plus actif, ou alerte absorbée par
        -- une plus ancienne (seuil abaissé). Fermées à la dernière minute du
        -- site : laissées en cours, elles resteraient affichées. Jamais les
        -- mêmes lignes que modifiees (NOT EXISTS).
        UPDATE gold.alerte AS a
        SET fin = greatest(
            a.debut,
            (
                SELECT max(sr.horodatage)
                FROM silver.silver_readings AS sr
                WHERE sr.id_site = a.id_site
            )
        )
        WHERE
            a.source = 'etl'
            AND a.type IN ('threshold', 'sensor')
            AND a.fin IS null
            AND NOT EXISTS (
                SELECT 1 FROM cibles AS c
                WHERE c.id_cible = a.id_alerte
            )
        RETURNING a.id_site, a.type, a.capteur, a.debut, false
    )

    SELECT * FROM modifiees
    UNION ALL
    SELECT * FROM nouvelles
    UNION ALL
    SELECT * FROM fermees;
END;
$$;

REVOKE ALL ON FUNCTION gold.detecter_alertes(INTERVAL) FROM public;
GRANT EXECUTE ON FUNCTION gold.detecter_alertes(INTERVAL) TO etl;

COMMIT;
