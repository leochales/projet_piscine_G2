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

CREATE OR REPLACE FUNCTION app.poser_seuil_alerte()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.seuil_alerte_pct IS null THEN
        NEW.seuil_alerte_pct := app.seuil_alerte_par_defaut(NEW.type);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_site_seuil_alerte
BEFORE INSERT ON app.site
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
-- transmet plus garde donc son alerte en cours.
-- Les pannes de capteur de l'API Mock durent presque toutes moins d'une
-- minute : sans la règle des 3 minutes, il y aurait 58 alertes par jour et
-- par capteur, contre 0,1.
-- C'est pourquoi la panne est lue dans silver (null_reasons), et non dans
-- gold.etat_capteur (SMARTOPS-23) : ce dernier donne l'état instantané de
-- l'API, sans la règle des 3 minutes. Un capteur peut donc y être en panne
-- sans qu'aucune alerte ne soit ouverte : c'est voulu.
--
-- Fenêtre : par site, les `fenetre` dernières minutes de silver, élargies au
-- début des alertes en cours ou récentes, pour retrouver la même alerte à
-- chaque passage. Le temps de référence est la dernière minute du site, et
-- non now() : silver en retard ne ferme rien à tort.
-- Une alerte en cours que le calcul ne retrouve plus (seuil modifié, minute
-- réécrite, site désactivé) est fermée à la dernière minute de son site.
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
        -- least() ignore NULL : sans alerte en cours ni récente, la fenêtre
        SELECT
            u.*,
            least(
                u.ref - fenetre,
                (
                    SELECT min(a.debut)
                    FROM gold.alerte AS a
                    WHERE
                        a.id_site = u.id_site
                        AND a.source = 'etl'
                        AND a.type = u.type
                        AND a.capteur IS NOT DISTINCT FROM u.capteur
                        AND (a.fin IS null OR a.fin >= u.ref - fenetre)
                )
            ) AS depuis
        FROM suivis AS u
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

    series AS (
        -- Suites de minutes consécutives dans le même état (îlots)
        SELECT
            id_site,
            type,
            capteur,
            en_defaut,
            min(horodatage) AS debut,
            count(*) AS nb
        FROM (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY id_site, type, capteur ORDER BY horodatage
                )
                - row_number() OVER (
                    PARTITION BY id_site, type, capteur, en_defaut
                    ORDER BY horodatage
                ) AS ilot
            FROM minutes
        ) AS x
        GROUP BY id_site, type, capteur, en_defaut, ilot
    ),

    franches AS (
        -- Seules les suites d'au moins 3 minutes changent l'état de l'alerte
        SELECT
            *,
            lag(en_defaut) OVER (
                PARTITION BY id_site, type, capteur ORDER BY debut
            ) AS precedente
        FROM series
        WHERE nb >= 3
    ),

    alertes AS (
        -- Début : une suite en défaut après une suite sans défaut (ou aucune).
        -- Fin : la première suite sans défaut qui la suit.
        SELECT
            o.id_site,
            o.type,
            o.capteur,
            o.debut,
            (
                SELECT min(f.debut)
                FROM franches AS f
                WHERE
                    f.id_site = o.id_site
                    AND f.type = o.type
                    AND f.capteur IS NOT DISTINCT FROM o.capteur
                    AND NOT f.en_defaut
                    AND f.debut > o.debut
            ) AS fin
        FROM franches AS o
        WHERE o.en_defaut AND o.precedente IS DISTINCT FROM true
    ),

    detail AS (
        SELECT
            a.*,
            (
                SELECT max(m.kw)
                FROM minutes AS m
                WHERE
                    m.id_site = a.id_site
                    AND m.type = a.type
                    AND m.capteur IS NOT DISTINCT FROM a.capteur
                    AND m.horodatage >= a.debut
                    AND (a.fin IS null OR m.horodatage < a.fin)
            ) AS valeur,
            u.seuil,
            u.capacite_kw
        FROM alertes AS a
        INNER JOIN suivis AS u
            ON
                a.id_site = u.id_site
                AND a.type = u.type
                AND a.capteur IS NOT DISTINCT FROM u.capteur
    ),

    ecrites AS (
        INSERT INTO gold.alerte AS a (
            id_site, source, type, capteur, severite, message,
            debut, fin, valeur, seuil
        )
        SELECT
            d.id_site,
            'etl',
            d.type,
            d.capteur,
            CASE
                WHEN d.capteur = 'electrical' THEN 'medium'
                WHEN d.type = 'threshold' AND d.valeur >= d.capacite_kw * 1.1
                    THEN 'critical'
                ELSE 'high'
            END,
            CASE
                WHEN d.type = 'threshold'
                    THEN format(
                        'Seuil d''alerte dépassé : jusqu''à %s kW pour un '
                        'seuil de %s kW',
                        d.valeur, d.seuil
                    )
                WHEN d.capteur = 'consumption'
                    THEN 'Capteur de consommation en panne'
                ELSE 'Capteur électrique en panne'
            END,
            d.debut,
            d.fin,
            -- Valeur et seuil n'ont de sens que pour un dépassement
            CASE WHEN d.type = 'threshold' THEN d.valeur END,
            CASE WHEN d.type = 'threshold' THEN d.seuil END
        FROM detail AS d
        ON CONFLICT (id_site, type, capteur, debut) WHERE source = 'etl'
        DO UPDATE SET
            severite = excluded.severite,
            message = excluded.message,
            fin = excluded.fin,
            valeur = excluded.valeur,
            seuil = excluded.seuil
        -- Une alerte inchangée n'est pas réécrite (ni comptée)
        WHERE
            (a.severite, a.message, a.fin, a.valeur, a.seuil)
            IS DISTINCT FROM
            (
                excluded.severite, excluded.message, excluded.fin,
                excluded.valeur, excluded.seuil
            )
        RETURNING a.id_site, a.type, a.capteur, a.debut, a.fin IS null
    ),

    fermees AS (
        -- Alertes en cours que le calcul ne retrouve plus : début décalé
        -- (seuil modifié, minute de silver réécrite) ou site qui n'est plus
        -- actif. Fermées à la dernière minute du site : laissées en cours,
        -- elles resteraient affichées et élargiraient la fenêtre (depart) à
        -- chaque passage. Jamais les mêmes lignes que ecrites (NOT EXISTS).
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
                SELECT 1
                FROM detail AS d
                WHERE
                    d.id_site = a.id_site
                    AND d.type = a.type
                    AND d.capteur IS NOT DISTINCT FROM a.capteur
                    AND d.debut = a.debut
            )
        RETURNING a.id_site, a.type, a.capteur, a.debut, false
    )

    SELECT * FROM ecrites
    UNION ALL
    SELECT * FROM fermees;
END;
$$;

REVOKE ALL ON FUNCTION gold.detecter_alertes(INTERVAL) FROM public;
GRANT EXECUTE ON FUNCTION gold.detecter_alertes(INTERVAL) TO etl;

COMMIT;
