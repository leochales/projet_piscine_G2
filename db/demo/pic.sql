-- =============================================================================
-- EnerVision : pic de consommation pour la démo
--
-- Pendant quelques minutes, chaque mesure collectée d'un site arrive en bronze
-- au-dessus de son seuil d'alerte. La collecte continue normalement : un
-- trigger temporaire remplace seulement la consommation (et l'intensité) des
-- mesures de l'API Mock, à la minute où elles arrivent. L'ETL fait le reste :
-- silver, gold (consommation, dernière mesure), l'alerte threshold après
-- 3 minutes au-dessus du seuil, puis sa recommandation.
--
-- Pas de minutes écrites à l'avance : silver traite bronze jusqu'à sa dernière
-- ligne, une mesure future deviendrait la « dernière mesure » du site.
--
-- L'alerte apparaît 4 à 5 minutes après le lancement et se ferme 3 minutes
-- après la fin du pic : lancer ce script 5 minutes avant d'enregistrer, avec un
-- pic plus long que le tournage : db/demo/reset.sql remet les boutons entre
-- deux prises sans arrêter le pic, db/demo/fin_pic.sql l'arrête à la fin.
--
-- Base de dev ou locale, avec le compte admin PostgreSQL :
--   docker exec -i postgres \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/demo/pic.sql
-- Paramètres facultatifs, avec PGOPTIONS (voir .github/workflows/demo.yml) :
--   demo.site (SITE001), demo.minutes (90), demo.charge (1.15 = 115 % de la
--   capacité, sévérité critical au-delà de 110 %)
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS bronze.demo_pic (
    id_site VARCHAR(20) PRIMARY KEY REFERENCES app.site (id_site),
    jusqu_a TIMESTAMPTZ NOT NULL,
    charge NUMERIC(4, 2) NOT NULL CHECK (charge > 0 AND charge < 2)
);

-- Droits du propriétaire : la collecte écrit avec le compte etl, qui ne lit
-- ni bronze.demo_pic ni la capacité des sites
CREATE OR REPLACE FUNCTION bronze.demo_pic_appliquer()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_kw numeric;
    v_ancien numeric;
BEGIN
    SELECT round(
        s.capacite_kw * p.charge * (0.98 + random() * 0.04)::numeric, 2
    )
    INTO v_kw
    FROM bronze.demo_pic AS p
    INNER JOIN app.site AS s ON p.id_site = s.id_site
    WHERE p.id_site = NEW.id_site AND NEW.horodatage <= p.jusqu_a;

    IF v_kw IS null THEN
        RETURN NEW;
    END IF;

    -- L'API Mock simule des pannes du capteur de consommation : pendant le
    -- pic, la consommation est toujours donnée, sinon l'alerte n'atteint pas
    -- 3 minutes consécutives
    v_ancien := (NEW.payload ->> 'consumption_kw')::numeric;
    NEW.payload := NEW.payload || jsonb_build_object(
        'consumption_kw', v_kw,
        'consumption_kwh', v_kw,
        'null_reasons', coalesce(
            (
                SELECT jsonb_agg(r.raison)
                FROM jsonb_array_elements(NEW.payload -> 'null_reasons') AS r (raison)
                WHERE r.raison <> '"consumption_sensor_failure"'::jsonb
            ),
            '[]'::jsonb
        )
    );
    IF v_ancien > 0 AND NEW.payload ->> 'current_a' IS NOT null THEN
        NEW.payload := NEW.payload || jsonb_build_object(
            'current_a',
            round((NEW.payload ->> 'current_a')::numeric * v_kw / v_ancien, 2)
        );
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER trg_demo_pic
BEFORE INSERT ON bronze.raw_readings
FOR EACH ROW EXECUTE FUNCTION bronze.demo_pic_appliquer();

DO $$
DECLARE
    v_site CONSTANT varchar := coalesce(
        nullif(current_setting('demo.site', true), ''), 'SITE001'
    );
    v_minutes CONSTANT integer := coalesce(
        nullif(current_setting('demo.minutes', true), ''), '90'
    )::integer;
    v_charge CONSTANT numeric := coalesce(
        nullif(current_setting('demo.charge', true), ''), '1.15'
    )::numeric;
    v_seuil numeric;
    v_jusqu_a timestamptz;
BEGIN
    SELECT s.seuil_alerte_pct INTO v_seuil
    FROM app.site AS s
    WHERE s.id_site = v_site AND s.statut = 'active';

    IF NOT found THEN
        RAISE EXCEPTION 'site % inconnu ou inactif', v_site;
    END IF;
    IF v_minutes NOT BETWEEN 5 AND 180 THEN
        RAISE EXCEPTION 'demo.minutes doit être entre 5 et 180 (%)', v_minutes;
    END IF;
    IF v_charge * 100 <= v_seuil OR v_charge >= 2 THEN
        RAISE EXCEPTION
            'demo.charge % : au-dessus du seuil du site (% %%), sous 2',
            v_charge, v_seuil;
    END IF;

    v_jusqu_a := date_trunc('minute', now()) + v_minutes * interval '1 minute';

    INSERT INTO bronze.demo_pic (id_site, jusqu_a, charge)
    VALUES (v_site, v_jusqu_a, v_charge)
    ON CONFLICT (id_site) DO UPDATE SET
        jusqu_a = excluded.jusqu_a,
        charge = excluded.charge;

    RAISE NOTICE 'pic sur % à % %% de la capacité (seuil % %%), jusqu''à % UTC',
        v_site, round(v_charge * 100), v_seuil, to_char(v_jusqu_a, 'HH24:MI');
END
$$;

COMMIT;
