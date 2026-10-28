-- =============================================================================
-- Tests de la vue de supervision (db/19_supervision_metier.sql)
--
-- Le compte monitoring lit les totaux et ne lit pas les tables métier.
-- L'ETL commit chaque minute pendant la CI. Cette transaction ne voit pas
-- ces commits entre ses deux lectures de la vue. Tout est annulé (ROLLBACK).
-- =============================================================================

-- Vaut pour la transaction ouverte juste après. Remis à la fin du script.
SET default_transaction_isolation TO 'repeatable read';

BEGIN;

INSERT INTO app.client (nom) VALUES ('Client test supervision');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw, statut)
SELECT
    v.id_site,
    (
        SELECT cl.id_client FROM app.client AS cl
        WHERE cl.nom = 'Client test supervision'
    ) AS id_client,
    v.nom,
    'office' AS type,  -- noqa: RF04
    500 AS capacite_kw,
    v.statut
FROM (
    VALUES
    ('SITE-SUP', 'Site test supervision', 'active'),
    ('SITE-OFF', 'Site inactif', 'inactive'),
    ('SITE-MUET', 'Site qui ne transmet plus', 'active')
) AS v (id_site, nom, statut);

DO $$
DECLARE
    avant gold.supervision_metier%ROWTYPE;
    apres gold.supervision_metier%ROWTYPE;
    -- Heure pleine déjà écoulée, dans les 24 h : la vue ignore l'heure en cours.
    heure_passee CONSTANT timestamptz
        := date_trunc('hour', now()) - interval '1 hour';
    -- Hors fenêtre de 24 h : ne doit entrer ni dans l'écart ni dans l'imputation.
    heure_ancienne CONSTANT timestamptz
        := date_trunc('hour', now()) - interval '48 hours';
    ingestion_recente CONSTANT timestamptz := now();
    somme_ecarts numeric;
    somme_reelle numeric;
    somme_imputees numeric;
    somme_mesures numeric;
    ecart_attendu double precision;
    taux_attendu double precision;
    interdites CONSTANT text[] := ARRAY[
        'SELECT * FROM bronze.raw_readings',
        'SELECT * FROM silver.silver_readings',
        'SELECT * FROM gold.prediction',
        'SELECT * FROM gold.alerte',
        'SELECT * FROM gold.derniere_mesure',
        'SELECT * FROM gold.consommation_horaire',
        'SELECT * FROM app.site'
    ];
    requete text;
BEGIN
    SELECT * INTO avant FROM gold.supervision_metier;

    -- Même périmètre que la vue, avant les lignes de ce test.
    SELECT
        coalesce(
            sum(abs(p.consommation_prevue_kwh - c.consommation_kwh)),
            0
        ),
        coalesce(sum(c.consommation_kwh), 0)
    INTO somme_ecarts, somme_reelle
    FROM (
        SELECT DISTINCT ON (id_site, heure_prevue)
            id_site,
            heure_prevue,
            consommation_prevue_kwh
        FROM gold.prediction
        WHERE
            heure_prevue >= date_trunc('hour', now()) - interval '24 hours'
            AND heure_prevue < date_trunc('hour', now())
        ORDER BY id_site ASC, heure_prevue ASC, calculee_le DESC
    ) AS p
    INNER JOIN gold.consommation_horaire AS c
        ON p.id_site = c.id_site AND p.heure_prevue = c.heure
    WHERE
        c.consommation_kwh IS NOT null
        AND c.heure_complete;

    SELECT
        coalesce(sum(h.nb_imputees), 0),
        coalesce(sum(h.nb_mesures), 0)
    INTO somme_imputees, somme_mesures
    FROM gold.consommation_horaire AS h
    INNER JOIN app.site AS s ON h.id_site = s.id_site
    WHERE
        s.statut = 'active'
        AND h.heure_complete
        AND h.heure >= date_trunc('hour', now()) - interval '24 hours'
        AND h.heure < date_trunc('hour', now());

    -- Minute la plus récente, enregistrée il y a 2 jours : ce n'est pas
    -- la dernière collecte, et elle est hors des 24 h comptées.
    -- Minute ancienne rattrapée maintenant : c'est la collecte, et elle compte.
    -- Le site inactif a un enregistrement encore plus récent : ignoré.
    INSERT INTO bronze.raw_readings (id_site, horodatage, ingested_at, payload)
    VALUES
    ('SITE-SUP', now(), ingestion_recente - interval '2 days', '{}'),
    ('SITE-SUP', now() - interval '1 day', ingestion_recente, '{}'),
    ('SITE-OFF', now(), ingestion_recente + interval '1 hour', '{}');

    INSERT INTO gold.derniere_mesure (
        id_site, horodatage, consommation_kw, data_quality
    ) VALUES
    ('SITE-SUP', now(), 80, 'good'),
    ('SITE-OFF', now(), 500, 'good'),
    ('SITE-MUET', heure_passee, 40, 'good');

    INSERT INTO gold.consommation_horaire (
        id_site, heure, consommation_kwh, nb_mesures, nb_imputees, heure_complete
    ) VALUES
    ('SITE-SUP', heure_passee, 100, 60, 12, true),
    -- 999 prévu pour 100 réel : heure incomplète, hors de l'écart.
    ('SITE-SUP', heure_passee - interval '1 hour', 100, 10, 10, false),
    -- Heure complète trop ancienne : hors de l'écart et du taux.
    ('SITE-SUP', heure_ancienne, 100, 60, 60, true),
    -- Site inactif, heure complète récente : hors du taux.
    ('SITE-OFF', heure_passee, 100, 60, 60, true);

    INSERT INTO gold.prediction (
        id_site, heure_prevue, consommation_prevue_kwh, version_modele, calculee_le
    ) VALUES
    -- Une prévision plus ancienne de la même heure ne doit pas gagner.
    ('SITE-SUP', heure_passee, 500, 'test', now() - interval '1 hour'),
    ('SITE-SUP', heure_passee, 110, 'test', now()),
    ('SITE-SUP', heure_passee - interval '1 hour', 999, 'test', now()),
    ('SITE-SUP', heure_ancienne, 999, 'test', now());

    INSERT INTO gold.alerte (id_site, source, type, severite, debut)
    VALUES
    ('SITE-SUP', 'etl', 'threshold', 'high', heure_passee),
    ('SITE-OFF', 'etl', 'threshold', 'high', heure_passee);

    SET ROLE monitoring;
    SELECT * INTO apres FROM gold.supervision_metier;

    ASSERT apres.mesures_collectees = avant.mesures_collectees + 1,
    'seule la mesure enregistrée depuis 24 h d''un site actif compte';
    -- 12 imputées sur 60 minutes, heures complètes des dernières 24 h.
    taux_attendu := (
        100 * (somme_imputees + 12) / (somme_mesures + 60)
    )::double precision;
    ASSERT apres.valeurs_imputees = taux_attendu,
    'le taux d''imputation ignore l''heure ancienne, l''incomplète et le site inactif';
    ASSERT apres.puissance_kw = avant.puissance_kw + 80,
    'la puissance ignore le site inactif et celui qui ne transmet plus';
    ASSERT apres.previsions_ecrites = avant.previsions_ecrites + 4,
    'les quatre prévisions insérées doivent être comptées';
    ASSERT apres.alertes_en_cours = avant.alertes_en_cours + 1,
    'l''alerte du site inactif ne compte pas';
    ASSERT apres.derniere_collecte_epoch = extract(EPOCH FROM ingestion_recente),
    'la dernière collecte est la date d''enregistrement, pas celle de la minute';
    ASSERT apres.dernier_calcul_epoch IS NOT null,
    'le dernier calcul doit avoir un horodatage';
    -- 110 prévu, 100 réel : +10 au numérateur, +100 au dénominateur.
    -- L'heure incomplète, l'heure ancienne et la prévision périmée restent dehors.
    ecart_attendu := (
        100 * (somme_ecarts + 10) / (somme_reelle + 100)
    )::double precision;
    ASSERT apres.ecart_prevu_reel_pct = ecart_attendu,
    'l''écart porte sur les heures complètes des dernières 24 h';

    FOREACH requete IN ARRAY interdites LOOP
        BEGIN
            EXECUTE requete;
            RAISE EXCEPTION 'devrait être refusé à monitoring : %', requete;
        EXCEPTION WHEN insufficient_privilege THEN
            null;
        END;
    END LOOP;
    RESET ROLE;
    RAISE NOTICE 'OK : monitoring lit les totaux, pas les tables';
END
$$;

ROLLBACK;

RESET default_transaction_isolation;
