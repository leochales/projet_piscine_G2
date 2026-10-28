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

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES (
    'SITE-SUP',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test supervision'
    ),
    'Site test supervision',
    'office',
    500
);

DO $$
DECLARE
    avant gold.supervision_metier%ROWTYPE;
    apres gold.supervision_metier%ROWTYPE;
    -- Heure pleine déjà écoulée : la vue ignore l'heure en cours.
    heure_passee CONSTANT timestamptz
        := date_trunc('hour', now()) - interval '1 hour';
    somme_ecarts numeric;
    somme_reelle numeric;
    ecart_attendu double precision;
    interdites CONSTANT text[] := ARRAY[
        'SELECT * FROM bronze.raw_readings',
        'SELECT * FROM silver.silver_readings',
        'SELECT * FROM gold.prediction',
        'SELECT * FROM gold.alerte',
        'SELECT * FROM gold.derniere_mesure'
    ];
    requete text;
BEGIN
    SELECT * INTO avant FROM gold.supervision_metier;

    -- Même périmètre que la vue, avant les lignes de ce test : le pourcentage
    -- attendu se recalcule même si gold a déjà des heures complètes.
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
        WHERE heure_prevue < date_trunc('hour', now())
        ORDER BY id_site ASC, heure_prevue ASC, calculee_le DESC
    ) AS p
    INNER JOIN gold.consommation_horaire AS c
        ON p.id_site = c.id_site AND p.heure_prevue = c.heure
    WHERE
        c.consommation_kwh IS NOT null
        AND c.heure_complete;

    INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
    VALUES ('SITE-SUP', heure_passee, '{}');

    INSERT INTO silver.silver_readings (
        id_site, horodatage, imputation_method, data_quality
    ) VALUES (
        'SITE-SUP', heure_passee, 'linear_interpolation', 'good'
    );

    INSERT INTO gold.derniere_mesure (
        id_site, horodatage, consommation_kw, data_quality
    ) VALUES ('SITE-SUP', heure_passee, 80, 'good');

    INSERT INTO gold.consommation_horaire (
        id_site, heure, consommation_kwh, nb_mesures, heure_complete
    ) VALUES
    ('SITE-SUP', heure_passee, 100, 60, true),
    -- 999 prévu pour 100 réel : ne doit pas entrer dans l'écart.
    ('SITE-SUP', heure_passee - interval '1 hour', 100, 10, false);

    INSERT INTO gold.prediction (
        id_site, heure_prevue, consommation_prevue_kwh, version_modele
    ) VALUES
    ('SITE-SUP', heure_passee, 110, 'test'),
    ('SITE-SUP', heure_passee - interval '1 hour', 999, 'test');

    INSERT INTO gold.alerte (id_site, source, type, severite, debut)
    VALUES ('SITE-SUP', 'etl', 'threshold', 'high', heure_passee);

    SET ROLE monitoring;
    SELECT * INTO apres FROM gold.supervision_metier;

    ASSERT apres.mesures_collectees = avant.mesures_collectees + 1,
    'la collecte doit compter la mesure insérée';
    ASSERT apres.valeurs_imputees = avant.valeurs_imputees + 1,
    'l''imputation doit compter la ligne silver';
    ASSERT apres.puissance_kw = avant.puissance_kw + 80,
    'la puissance doit ajouter les 80 kW du site';
    ASSERT apres.previsions_ecrites = avant.previsions_ecrites + 2,
    'les deux prévisions insérées doivent être comptées';
    ASSERT apres.alertes_en_cours = avant.alertes_en_cours + 1,
    'l''alerte ouverte doit être comptée';
    ASSERT apres.derniere_collecte_epoch IS NOT null,
    'la dernière collecte doit avoir un horodatage';
    ASSERT apres.dernier_calcul_epoch IS NOT null,
    'le dernier calcul doit avoir un horodatage';
    -- 110 prévu, 100 réel : +10 au numérateur, +100 au dénominateur.
    -- L'heure incomplète (999 prévu) reste dehors.
    ecart_attendu := (
        100 * (somme_ecarts + 10) / (somme_reelle + 100)
    )::double precision;
    ASSERT apres.ecart_prevu_reel_pct = ecart_attendu,
    'l''écart ne compte que l''heure complète : 110 prévu pour 100 réel';

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
