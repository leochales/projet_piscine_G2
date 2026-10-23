-- =============================================================================
-- Tests de la dernière mesure et de l'état des sites
-- (db/13_gold_derniere_mesure.sql) et des droits des comptes etl et api
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

-- Données de test (superutilisateur) : trois sites actifs et un inactif
--   SITE-A : transmet, dernière mesure il y a 1 minute, suivie d'une minute
--            sans mesure (bronze_id NULL) à ignorer ;
--   SITE-B : ne transmet plus, dernière mesure il y a 20 minutes, suivie de
--            mesures « perte réseau » (reçues, mais toutes à null) à ignorer ;
--   SITE-C : n'a jamais transmis ;
--   SITE-I : inactif, ignoré même s'il a des mesures.
INSERT INTO app.client (nom) VALUES ('Client test derniere mesure');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw, statut)
SELECT
    v.id_site,
    (
        SELECT cl.id_client FROM app.client AS cl
        WHERE cl.nom = 'Client test derniere mesure'
    ) AS id_client,
    'Site ' || v.id_site AS nom,
    'office' AS type,  -- noqa: RF04
    500 AS capacite_kw,
    v.statut
FROM (
    VALUES
    ('SITE-A', 'active'),
    ('SITE-B', 'active'),
    ('SITE-C', 'active'),
    ('SITE-I', 'inactive')
) AS v (id_site, statut);

-- Mesures reçues (bronze), arrondies à la minute
INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
SELECT
    v.id_site,
    date_trunc('minute', now()) - v.age AS horodatage,
    '{}'::jsonb AS payload
FROM (
    VALUES
    ('SITE-A', interval '3 minutes'),
    ('SITE-A', interval '1 minute'),
    ('SITE-B', interval '20 minutes'),
    ('SITE-I', interval '1 minute')
) AS v (id_site, age);

-- silver : les mesures reçues, plus la minute suivante de SITE-A sans mesure
INSERT INTO silver.silver_readings (
    id_site, horodatage, bronze_id, consumption_kw_raw,
    consumption_kw_imputed, power_factor, temperature_celsius,
    data_quality, null_reasons
)
SELECT
    b.id_site,
    b.horodatage,
    b.id AS bronze_id,
    100 + extract(MINUTE FROM b.horodatage)::numeric AS consumption_kw_raw,
    100 + extract(MINUTE FROM b.horodatage)::numeric AS consumption_kw_imputed,
    0.95 AS power_factor,
    21.5 AS temperature_celsius,
    'good' AS data_quality,
    '{}' AS null_reasons
FROM bronze.raw_readings AS b
WHERE b.id_site LIKE 'SITE-_';

INSERT INTO silver.silver_readings (
    id_site, horodatage, data_quality, null_reasons
) VALUES (
    'SITE-A', date_trunc('minute', now()), 'critical', '{network_loss}'
);

-- Perte réseau de SITE-B depuis 10 minutes : l'API Mock répond quand même,
-- avec toutes les valeurs à null et la raison network_loss
INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
SELECT
    'SITE-B' AS id_site,
    date_trunc('minute', now()) - (n * interval '1 minute') AS horodatage,
    '{"null_reasons": ["network_loss"]}'::jsonb AS payload
FROM generate_series(0, 9) AS n;

INSERT INTO silver.silver_readings (
    id_site, horodatage, bronze_id, data_quality, null_reasons
)
SELECT
    b.id_site,
    b.horodatage,
    b.id AS bronze_id,
    'critical' AS data_quality,
    '{network_loss}' AS null_reasons
FROM bronze.raw_readings AS b
WHERE b.id_site = 'SITE-B' AND b.payload ? 'null_reasons';

-- État des capteurs : SITE-A sans panne, SITE-B en perte réseau
INSERT INTO gold.etat_capteur (id_site, capteur, statut, en_panne_jusqu_a)
SELECT
    v.id_site,
    c.capteur,
    CASE
        WHEN
            v.id_site = 'SITE-B' AND c.capteur = 'network'
            THEN 'failing'
        ELSE 'ok'
    END AS statut,
    CASE
        WHEN v.id_site = 'SITE-B' AND c.capteur = 'network'
            THEN now() + interval '10 minutes'
    END AS en_panne_jusqu_a
FROM (VALUES ('SITE-A'), ('SITE-B')) AS v (id_site)
CROSS JOIN (
    VALUES ('consumption'),
    ('electrical'),
    ('temperature'),
    ('humidity'),
    ('network')
) AS c (capteur);

-- À partir d'ici, mises à jour avec les droits du compte etl
SET ROLE etl;

-- 1. La fonction prend la dernière mesure reçue de chaque site actif
DO $$
DECLARE
    nb INTEGER;
    m gold.derniere_mesure;
BEGIN
    -- Au moins A et B (sur une base locale, les sites de démo peuvent s'y ajouter)
    nb := gold.mettre_a_jour_derniere_mesure();
    ASSERT nb >= 2, format('SITE-A et SITE-B attendus, %s site(s) mis à jour', nb);

    SELECT * INTO m FROM gold.derniere_mesure WHERE id_site = 'SITE-A';
    ASSERT m.horodatage = date_trunc('minute', now()) - interval '1 minute',
        'SITE-A : la minute sans mesure (bronze_id NULL) doit être ignorée';
    ASSERT m.consommation_kw = 100 + extract(MINUTE FROM m.horodatage),
        'SITE-A : mauvaise consommation';
    ASSERT m.facteur_puissance = 0.95 AND m.temperature_c = 21.5,
        'SITE-A : facteur de puissance ou température non repris';

    SELECT * INTO m FROM gold.derniere_mesure WHERE id_site = 'SITE-B';
    ASSERT m.horodatage = date_trunc('minute', now()) - interval '20 minutes'
        AND m.consommation_kw IS NOT null,
        'SITE-B : les mesures « perte réseau » doivent être ignorées';

    ASSERT NOT EXISTS (
        SELECT 1 FROM gold.derniere_mesure WHERE id_site IN ('SITE-C', 'SITE-I')
    ), 'un site sans mesure ou inactif ne doit pas avoir de dernière mesure';
    RAISE NOTICE 'OK 1 : dernière mesure reçue, sites sans mesure et inactifs ignorés';
END
$$;

-- 2. Rejouée sans nouvelle mesure, elle ne change rien
DO $$
DECLARE
    avant gold.derniere_mesure;
    apres gold.derniere_mesure;
BEGIN
    SELECT * INTO avant FROM gold.derniere_mesure WHERE id_site = 'SITE-A';
    PERFORM gold.mettre_a_jour_derniere_mesure();
    SELECT * INTO apres FROM gold.derniere_mesure WHERE id_site = 'SITE-A';
    ASSERT avant = apres, 'sans nouvelle mesure, SITE-A ne doit pas changer';
    RAISE NOTICE 'OK 2 : rejouable sans effet';
END
$$;

RESET ROLE;

-- 3. Une nouvelle mesure remplace l'ancienne ; une plus ancienne, jamais.
--    Le réseau de SITE-B revient il y a 2 minutes : cette minute devient une
--    vraie mesure (capteur de température en panne).
UPDATE silver.silver_readings
SET
    consumption_kw_raw = 250,
    data_quality = 'partial',
    null_reasons = '{temperature_sensor_failure}'
WHERE
    id_site = 'SITE-B'
    AND horodatage = date_trunc('minute', now()) - interval '2 minutes';

UPDATE gold.derniere_mesure SET horodatage = horodatage + interval '1 hour'
WHERE id_site = 'SITE-A';

SET ROLE etl;

DO $$
DECLARE
    m gold.derniere_mesure;
BEGIN
    PERFORM gold.mettre_a_jour_derniere_mesure();

    SELECT * INTO m FROM gold.derniere_mesure WHERE id_site = 'SITE-B';
    ASSERT m.consommation_kw = 250 AND m.data_quality = 'partial'
        AND m.null_reasons = '{temperature_sensor_failure}',
        'SITE-B : la nouvelle mesure doit remplacer l''ancienne';

    SELECT * INTO m FROM gold.derniere_mesure WHERE id_site = 'SITE-A';
    ASSERT m.horodatage > now(), 'SITE-A ne doit pas revenir à une mesure plus ancienne';
    RAISE NOTICE 'OK 3 : nouvelle mesure prise, jamais de retour en arrière';
END
$$;

RESET ROLE;

-- Remise en place de SITE-A et vieillissement de SITE-B pour la vue
UPDATE gold.derniere_mesure SET horodatage = horodatage - interval '1 hour'
WHERE id_site = 'SITE-A';
UPDATE gold.derniere_mesure SET horodatage = now() - interval '20 minutes'
WHERE id_site = 'SITE-B';

-- 4. La vue gold.etat_site, lue par l'API
SET ROLE api;

DO $$
DECLARE
    e gold.etat_site;
BEGIN
    ASSERT (SELECT count(*) FROM gold.etat_site WHERE id_site LIKE 'SITE-_') = 3,
        'la vue doit lister les 3 sites actifs, sans le site inactif';

    SELECT * INTO e FROM gold.etat_site WHERE id_site = 'SITE-A';
    ASSERT e.transmet AND e.etat_capteurs = 'ok' AND e.capteurs_en_panne = '{}',
        'SITE-A : transmet, capteurs ok';

    SELECT * INTO e FROM gold.etat_site WHERE id_site = 'SITE-B';
    ASSERT NOT e.transmet, 'SITE-B : sans mesure depuis 20 minutes, ne transmet plus';
    ASSERT e.etat_capteurs = 'critical' AND e.capteurs_en_panne = '{network}',
        'SITE-B : perte réseau, état critical';
    ASSERT e.retablissement_prevu > now(), 'SITE-B : rétablissement prévu attendu';

    SELECT * INTO e FROM gold.etat_site WHERE id_site = 'SITE-C';
    ASSERT NOT e.transmet AND e.derniere_mesure_le IS NULL AND e.etat_capteurs IS NULL,
        'SITE-C : jamais transmis, état des capteurs inconnu';
    RAISE NOTICE 'OK 4 : vue etat_site (transmission et capteurs)';
END
$$;

-- 5. Droits : l'API lit sans écrire ni appeler la fonction
DO $$
BEGIN
    BEGIN
        PERFORM gold.mettre_a_jour_derniere_mesure();
        RAISE EXCEPTION 'le compte api ne doit pas mettre à jour gold';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
    BEGIN
        UPDATE gold.derniere_mesure SET consommation_kw = 0;
        RAISE EXCEPTION 'le compte api ne doit pas modifier gold.derniere_mesure';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
    RAISE NOTICE 'OK 5 : api en lecture seule';
END
$$;

RESET ROLE;

ROLLBACK;
