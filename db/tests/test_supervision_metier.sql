-- =============================================================================
-- Tests de la vue de supervision (db/19_supervision_metier.sql)
--
-- Le compte monitoring lit les totaux et ne lit pas les tables métier.
-- Tout est annulé (ROLLBACK).
-- =============================================================================

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

    INSERT INTO bronze.raw_readings (id_site, horodatage, payload)
    VALUES ('SITE-SUP', '2026-10-28 10:00+00', '{}');

    INSERT INTO silver.silver_readings (
        id_site, horodatage, imputation_method, data_quality
    ) VALUES (
        'SITE-SUP', '2026-10-28 10:00+00', 'linear_interpolation', 'good'
    );

    INSERT INTO gold.derniere_mesure (
        id_site, horodatage, consommation_kw, data_quality
    ) VALUES ('SITE-SUP', '2026-10-28 10:00+00', 80, 'good');

    INSERT INTO gold.consommation_horaire (
        id_site, heure, consommation_kwh, nb_mesures
    ) VALUES ('SITE-SUP', '2026-10-28 09:00+00', 100, 60);

    INSERT INTO gold.prediction (
        id_site, heure_prevue, consommation_prevue_kwh, version_modele
    ) VALUES ('SITE-SUP', '2026-10-28 09:00+00', 110, 'test');

    INSERT INTO gold.alerte (id_site, source, type, severite, debut)
    VALUES ('SITE-SUP', 'etl', 'threshold', 'high', '2026-10-28 10:00+00');

    SET ROLE monitoring;
    SELECT * INTO apres FROM gold.supervision_metier;

    ASSERT apres.mesures_collectees = avant.mesures_collectees + 1,
    'la collecte doit compter la mesure insérée';
    ASSERT apres.valeurs_imputees = avant.valeurs_imputees + 1,
    'l''imputation doit compter la ligne silver';
    ASSERT apres.puissance_kw = avant.puissance_kw + 80,
    'la puissance doit ajouter les 80 kW du site';
    ASSERT apres.previsions_ecrites = avant.previsions_ecrites + 1,
    'la prévision insérée doit être comptée';
    ASSERT apres.alertes_en_cours = avant.alertes_en_cours + 1,
    'l''alerte ouverte doit être comptée';
    ASSERT apres.derniere_collecte_epoch IS NOT null,
    'la dernière collecte doit avoir un horodatage';
    ASSERT apres.dernier_calcul_epoch IS NOT null,
    'le dernier calcul doit avoir un horodatage';
    IF avant.ecart_prevu_reel_pct IS null THEN
        ASSERT apres.ecart_prevu_reel_pct = 10,
        '110 prévu pour 100 réel : écart de 10 %';
    END IF;

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
