-- =============================================================================
-- EnerVision : alertes de l'ETL dans gold (SMARTOPS-26)
-- 17 : seuil d'alerte par site, et détection des alertes depuis silver :
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

-- Pour les alertes de l'ETL : un capteur pour toute alerte sensor, et
-- seulement pour elles. Les autres sources (API Mock, modèle) ne donnent pas
-- de capteur. Supprimée puis recréée à chaque migration, pour que les bases
-- déjà migrées aient la dernière version (alerte_capteur_check, la première,
-- acceptait une alerte sensor sans capteur ; la deuxième valait pour toutes
-- les sources).
ALTER TABLE gold.alerte
DROP CONSTRAINT IF EXISTS alerte_capteur_check;

ALTER TABLE gold.alerte
DROP CONSTRAINT IF EXISTS alerte_capteur_type_check;

ALTER TABLE gold.alerte
ADD CONSTRAINT alerte_capteur_type_check CHECK (
    source <> 'etl'
    OR (
        (type = 'sensor') = (capteur IS NOT null)
        AND (capteur IS null OR capteur IN ('consumption', 'electrical'))
    )
);

-- Une alerte de l'ETL par site, type, capteur et début : chaque passage met à
-- jour l'alerte en cours au lieu d'en créer une nouvelle
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerte_etl
ON gold.alerte (id_site, type, capteur, debut) NULLS NOT DISTINCT
WHERE source = 'etl';


-- Moment du maximum atteint : dit si le maximum est avant la fenêtre de
-- calcul (définitif) ou dedans (une minute réécrite peut encore le baisser)
ALTER TABLE gold.alerte
ADD COLUMN IF NOT EXISTS valeur_le TIMESTAMPTZ;

COMMENT ON COLUMN gold.alerte.valeur_le IS
'Minute du maximum atteint (valeur), alertes threshold de l''ETL';


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
-- transmise ou refusée (no_reading, network_loss, rejected_reading) pour un
-- capteur. Un site qui ne
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
-- fenêtre et la recouvre (amorce) est reprise de gold.alerte, puis prolongée
-- ou fermée par les minutes de la fenêtre. Son maximum est repris s'il est
-- avant la fenêtre ; s'il est dedans et qu'une minute réécrite l'a baissé,
-- il est relu dans silver (cas rare). Le temps de référence est la dernière
-- minute du site, et non now() : silver en retard ne ferme rien à tort.
--
-- Les alertes recalculées sont rattachées aux lignes existantes, pour garder
-- leur identifiant (prise en compte, recommandation), par ordre de priorité :
--   1. la ligne en cours de même début ;
--   2. la ligne en cours que l'alerte recalculée recouvre (seuil abaissé :
--      l'alerte en cours garde sa ligne, même si elle rejoint une alerte plus
--      ancienne, qui reste dans l'historique telle quelle) ;
--   3. la ligne terminée de même début ;
--   4. la ligne, en cours ou terminée, qui la chevauche (minute réécrite).
-- Chaque ligne et chaque alerte gardent leur meilleur choix, s'il est
-- réciproque ; un second tour rattache celles dont le meilleur choix a été
-- pris par une autre.
-- Le début d'une ligne rattachée prend celui de l'alerte recalculée, sauf
-- si une autre ligne commence entre les deux : il reste alors le même.
-- Une ligne en cours que le calcul ne retrouve plus (défaut disparu, site
-- désactivé) est fermée à la dernière minute de son site.
--
-- Seuil écrit : celui du site, sauf si le maximum atteint est en dessous
-- (seuil relevé pendant l'alerte) : l'alerte garde le seuil qui l'a ouverte.
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
            am.valeur AS amorce_valeur,
            am.valeur_le AS amorce_valeur_le
        FROM suivis AS u
        LEFT JOIN LATERAL (
            SELECT a.debut, a.valeur, a.valeur_le
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
                ELSE NOT sr.null_reasons
                && ARRAY['no_reading', 'network_loss', 'rejected_reading']
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
        -- trou de plus de 5 minutes, avec leur maximum et sa minute
        SELECT
            id_site,
            type,
            capteur,
            en_defaut,
            min(horodatage) AS debut,
            count(*) AS nb,
            max(kw) AS kw_max,
            (array_agg(horodatage ORDER BY kw DESC NULLS LAST, horodatage))[1]
                AS kw_max_le
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

        -- L'amorce compte comme une suite en défaut, avant la fenêtre. Son
        -- maximum n'est repris que s'il est avant la fenêtre : dedans, il est
        -- recalculé avec les minutes de la fenêtre.
        SELECT
            id_site,
            type,
            capteur,
            true,
            amorce_debut,
            3,
            CASE
                WHEN amorce_valeur_le IS null OR amorce_valeur_le < depuis
                    THEN amorce_valeur
            END,
            CASE
                WHEN amorce_valeur_le IS null OR amorce_valeur_le < depuis
                    THEN amorce_valeur_le
            END
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
        -- Maximum atteint, et sa minute : sur les suites entre le début et
        -- la fin
        SELECT
            id_site,
            type,
            capteur,
            min(debut) FILTER (WHERE est_debut) AS debut,
            min(fin) AS fin,
            max(kw_max) FILTER (WHERE fin IS null OR debut < fin) AS valeur,
            (
                array_agg(kw_max_le ORDER BY kw_max DESC, kw_max_le)
                    FILTER (
                        WHERE (fin IS null OR debut < fin)
                        AND kw_max IS NOT null
                    )
            )[1] AS valeur_le
        FROM bornes
        GROUP BY id_site, type, capteur, episode
    ),

    detail AS (
        SELECT
            a.id_site,
            a.type,
            a.capteur,
            a.debut,
            a.fin,
            -- Maximum de l'amorce baissé par une minute réécrite dans la
            -- fenêtre : celui d'avant la fenêtre est relu dans silver
            CASE
                WHEN av.kw > a.valeur OR a.valeur IS null THEN av.kw
                ELSE a.valeur
            END AS valeur,
            CASE
                WHEN av.kw > a.valeur OR a.valeur IS null THEN av.horodatage
                ELSE a.valeur_le
            END AS valeur_le,
            u.seuil,
            u.capacite_kw,
            u.depuis
        FROM alertes AS a
        INNER JOIN depart AS u
            ON
                a.id_site = u.id_site
                AND a.type = u.type
                AND a.capteur IS NOT DISTINCT FROM u.capteur
        LEFT JOIN LATERAL (
            SELECT sr.consumption_kw_raw AS kw, sr.horodatage
            FROM silver.silver_readings AS sr
            WHERE
                a.type = 'threshold'
                AND a.debut = u.amorce_debut
                AND u.amorce_valeur_le >= u.depuis
                AND (a.valeur IS null OR a.valeur < u.amorce_valeur)
                AND sr.id_site = a.id_site
                AND sr.horodatage >= a.debut
                AND sr.horodatage < u.depuis
                AND sr.consumption_kw_raw IS NOT null
            ORDER BY sr.consumption_kw_raw DESC, sr.horodatage
            LIMIT 1
        ) AS av ON true
    ),

    existantes AS (
        -- Lignes de la base qu'une alerte recalculée peut reprendre : en
        -- cours, ou qui touchent la fenêtre
        SELECT e.id_alerte, e.id_site, e.type, e.capteur, e.debut, e.fin
        FROM gold.alerte AS e
        INNER JOIN depart AS u
            ON
                e.id_site = u.id_site
                AND e.type = u.type
                AND e.capteur IS NOT DISTINCT FROM u.capteur
        WHERE
            e.source = 'etl'
            AND (e.fin IS null OR e.fin > u.depuis OR e.debut >= u.depuis)
    ),

    paires AS (
        -- Rattachements possibles, par priorité (voir l'en-tête)
        SELECT
            e.id_alerte,
            d.id_site,
            d.type,
            d.capteur,
            d.debut,
            CASE
                WHEN e.fin IS null AND e.debut = d.debut THEN 1
                WHEN
                    e.fin IS null
                    AND d.debut <= e.debut
                    AND (d.fin IS null OR d.fin > e.debut)
                    THEN 2
                WHEN e.debut = d.debut THEN 3
                WHEN
                    d.debut < coalesce(e.fin, 'infinity')
                    AND e.debut < coalesce(d.fin, 'infinity')
                    THEN 4
            END AS rang,
            abs(extract(EPOCH FROM d.debut - e.debut)) AS ecart
        FROM detail AS d
        INNER JOIN existantes AS e
            ON
                d.id_site = e.id_site
                AND d.type = e.type
                AND d.capteur IS NOT DISTINCT FROM e.capteur
    ),

    retenues_1 AS (
        -- Chaque alerte recalculée et chaque ligne gardent leur meilleur
        -- rattachement ; seuls les choix réciproques sont retenus : une ligne
        -- n'est reprise qu'une fois, une alerte ne reprend qu'une ligne
        SELECT p.*
        FROM (
            SELECT DISTINCT ON (id_site, type, capteur, debut) *
            FROM paires
            WHERE rang IS NOT null
            ORDER BY id_site, type, capteur, debut, rang, ecart
        ) AS p
        INNER JOIN (
            SELECT DISTINCT ON (id_alerte) *
            FROM paires
            WHERE rang IS NOT null
            ORDER BY id_alerte, rang, ecart
        ) AS q
            ON
                p.id_alerte = q.id_alerte
                AND p.id_site = q.id_site
                AND p.type = q.type
                AND p.capteur IS NOT DISTINCT FROM q.capteur
                AND p.debut = q.debut
    ),

    restantes AS (
        -- Rattachements encore possibles : ni l'alerte ni la ligne ne sont
        -- prises au premier tour. Sans ce second tour, une ligne dont le
        -- meilleur choix est pris ailleurs serait fermée, et son alerte
        -- recréée sous un autre identifiant (alertes qui se chevauchent,
        -- seuil modifié)
        SELECT p.*
        FROM paires AS p
        WHERE
            p.rang IS NOT null
            AND NOT EXISTS (
                SELECT 1 FROM retenues_1 AS r
                WHERE r.id_alerte = p.id_alerte
            )
            AND NOT EXISTS (
                SELECT 1 FROM retenues_1 AS r
                WHERE
                    r.id_site = p.id_site
                    AND r.type = p.type
                    AND r.capteur IS NOT DISTINCT FROM p.capteur
                    AND r.debut = p.debut
            )
    ),

    retenues AS (
        -- Choix réciproques du premier tour, puis du second
        SELECT * FROM retenues_1
        UNION ALL
        SELECT p.*
        FROM (
            SELECT DISTINCT ON (id_site, type, capteur, debut) *
            FROM restantes
            ORDER BY id_site, type, capteur, debut, rang, ecart
        ) AS p
        INNER JOIN (
            SELECT DISTINCT ON (id_alerte) *
            FROM restantes
            ORDER BY id_alerte, rang, ecart
        ) AS q
            ON
                p.id_alerte = q.id_alerte
                AND p.id_site = q.id_site
                AND p.type = q.type
                AND p.capteur IS NOT DISTINCT FROM q.capteur
                AND p.debut = q.debut
    ),

    cibles AS (
        -- Ligne à mettre à jour (vide : alerte nouvelle) et valeurs à écrire
        SELECT
            d.id_site,
            d.type,
            d.capteur,
            r.id_alerte AS id_cible,
            -- Début de l'alerte recalculée, sauf si une autre ligne commence
            -- entre les deux : l'index unique interdirait deux lignes de même
            -- début, et l'historique reste tel quel
            CASE
                WHEN
                    t.id_alerte IS NOT null
                    AND EXISTS (
                        SELECT 1 FROM gold.alerte AS o
                        WHERE
                            o.source = 'etl'
                            AND o.id_site = t.id_site
                            AND o.type = t.type
                            AND o.capteur IS NOT DISTINCT FROM t.capteur
                            AND o.id_alerte <> t.id_alerte
                            AND o.debut >= least(d.debut, t.debut)
                            AND o.debut <= greatest(d.debut, t.debut)
                    )
                    THEN t.debut
                ELSE d.debut
            END AS debut,
            d.fin,
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
            CASE WHEN d.type = 'threshold' THEN d.valeur_le END AS valeur_le,
            CASE
                WHEN d.type <> 'threshold' THEN null
                -- Seuil relevé pendant l'alerte : elle garde celui qui l'a
                -- ouverte
                WHEN d.valeur < d.seuil THEN coalesce(t.seuil, d.seuil)
                ELSE d.seuil
            END AS seuil
        FROM detail AS d
        LEFT JOIN retenues AS r
            ON
                d.id_site = r.id_site
                AND d.type = r.type
                AND d.capteur IS NOT DISTINCT FROM r.capteur
                AND d.debut = r.debut
        LEFT JOIN gold.alerte AS t ON r.id_alerte = t.id_alerte
    ),

    modifiees AS (
        UPDATE gold.alerte AS a
        SET
            debut = c.debut,
            fin = c.fin,
            severite = c.severite,
            message = c.message,
            valeur = c.valeur,
            valeur_le = c.valeur_le,
            seuil = c.seuil
        FROM cibles AS c
        WHERE
            a.id_alerte = c.id_cible
            -- Une alerte inchangée n'est pas réécrite (ni comptée)
            AND (
                a.debut, a.fin, a.severite, a.message, a.valeur, a.valeur_le,
                a.seuil
            )
            IS DISTINCT FROM
            (
                c.debut, c.fin, c.severite, c.message, c.valeur, c.valeur_le,
                c.seuil
            )
        RETURNING a.id_site, a.type, a.capteur, a.debut, a.fin IS null
    ),

    nouvelles AS (
        INSERT INTO gold.alerte AS a (
            id_site, source, type, capteur, severite, message,
            debut, fin, valeur, valeur_le, seuil
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
            c.valeur_le,
            c.seuil
        FROM cibles AS c
        WHERE c.id_cible IS null
        -- Deux passages en même temps, ou alerte recouvrant une ligne déjà
        -- reprise de même début : rien n'est écrit
        ON CONFLICT (id_site, type, capteur, debut) WHERE source = 'etl'
        DO NOTHING
        RETURNING a.id_site, a.type, a.capteur, a.debut, a.fin IS null
    ),

    fermees AS (
        -- Lignes en cours que le calcul ne retrouve plus : défaut disparu
        -- (seuil relevé) ou site qui n'est plus actif. Fermées à la dernière
        -- minute du site : laissées en cours, elles resteraient affichées.
        -- Site sans plus aucune minute dans silver (purgé) : fermées
        -- maintenant, et non avec une durée nulle.
        -- Jamais les mêmes lignes que modifiees (NOT EXISTS).
        UPDATE gold.alerte AS a
        SET fin = greatest(
            a.debut,
            coalesce(
                (
                    SELECT max(sr.horodatage)
                    FROM silver.silver_readings AS sr
                    WHERE sr.id_site = a.id_site
                ),
                now()
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
