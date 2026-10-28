-- =============================================================================
-- Tests des alertes de pic prévu du modèle (db/19_alerte_modele.sql) : une
-- seule alerte en cours par site, mise à jour par INSERT ... ON CONFLICT et
-- terminée comme le fait model/alerte_pic.py, avec les droits du compte model
--
-- Les requêtes de model/alerte_pic.py sont reprises dans deux fonctions
-- temporaires (pg_temp), à garder identiques. Les heures sont relatives à
-- now() : la règle du début dépend du moment présent.
--
-- Lancé par la CI (.github/workflows/images.yml) sur une base neuve, avec
-- le superutilisateur. Tout est annulé à la fin (ROLLBACK) : aucune donnée ne
-- reste. Un échec arrête le script (psql -v ON_ERROR_STOP=1).
-- =============================================================================

BEGIN;

INSERT INTO app.client (nom) VALUES ('Client test alerte modèle');

INSERT INTO app.site (id_site, id_client, nom, type, capacite_kw) VALUES (
    'SITE-M',
    (
        SELECT id_client FROM app.client
        WHERE nom = 'Client test alerte modèle'
    ),
    'Site test alerte modèle',
    'office',
    500
);

-- INSERT ... ON CONFLICT de alerte_pic.mettre_a_jour
CREATE FUNCTION pg_temp.ecrire_pic(
    p_severite VARCHAR,
    p_debut TIMESTAMPTZ,
    p_valeur NUMERIC,
    p_valeur_le TIMESTAMPTZ
) RETURNS VOID
LANGUAGE sql
AS $$
    INSERT INTO gold.alerte (
        id_site, source, type, severite, debut, valeur, valeur_le, seuil
    )
    VALUES (
        'SITE-M', 'modele', 'predicted_peak', p_severite, p_debut,
        p_valeur, p_valeur_le, 450
    )
    ON CONFLICT (id_site, type)
    WHERE source = 'modele' AND fin IS null
    DO UPDATE SET
        severite = excluded.severite,
        valeur = excluded.valeur,
        valeur_le = excluded.valeur_le,
        seuil = excluded.seuil,
        debut = CASE
            WHEN gold.alerte.debut > now() THEN excluded.debut
            ELSE gold.alerte.debut
        END;
$$;

-- UPDATE de alerte_pic.terminer
CREATE FUNCTION pg_temp.terminer(p_sites VARCHAR[]) RETURNS VOID
LANGUAGE sql
AS $$
    UPDATE gold.alerte
    SET fin = now(), debut = least(debut, now())
    WHERE source = 'modele'
      AND type = 'predicted_peak'
      AND fin IS null
      AND (
          id_site = ANY(p_sites)
          OR coalesce(valeur_le, debut) + INTERVAL '1 hour' <= now()
      );
$$;

GRANT EXECUTE ON FUNCTION pg_temp.ecrire_pic(
    VARCHAR, TIMESTAMPTZ, NUMERIC, TIMESTAMPTZ
) TO model;
GRANT EXECUTE ON FUNCTION pg_temp.terminer(VARCHAR[]) TO model;

SET ROLE model;

-- 1. Pic prévu dans 2 h, puis décalé à 4 h : une seule alerte, dont le début
-- (encore à venir) suit la prévision
SELECT pg_temp.ecrire_pic(
    'high', date_trunc('hour', now()) + INTERVAL '2 hours', 460,
    date_trunc('hour', now()) + INTERVAL '3 hours'
);
SELECT pg_temp.ecrire_pic(
    'critical', date_trunc('hour', now()) + INTERVAL '4 hours', 560,
    date_trunc('hour', now()) + INTERVAL '5 hours'
);

DO $$
DECLARE
    a RECORD;
    n INTEGER;
BEGIN
    SELECT count(*) INTO n FROM gold.alerte
    WHERE id_site = 'SITE-M' AND source = 'modele';
    ASSERT n = 1, format('une seule alerte attendue, %s trouvées', n);

    SELECT * INTO a FROM gold.alerte
    WHERE id_site = 'SITE-M' AND source = 'modele';
    ASSERT a.severite = 'critical', format('sévérité %s', a.severite);
    ASSERT a.valeur = 560, format('valeur %s', a.valeur);
    ASSERT a.debut = date_trunc('hour', now()) + INTERVAL '4 hours',
    format('début %s : il devait suivre la prévision', a.debut);
    RAISE NOTICE 'OK 1 : alerte mise à jour sans doublon, début à venir suivi';
END
$$;

-- 2. Début atteint : il ne change plus
UPDATE gold.alerte SET debut = date_trunc('hour', now()) - INTERVAL '1 hour'
WHERE id_site = 'SITE-M' AND source = 'modele' AND fin IS null;

SELECT pg_temp.ecrire_pic(
    'high', date_trunc('hour', now()) + INTERVAL '3 hours', 470,
    date_trunc('hour', now()) + INTERVAL '3 hours'
);

DO $$
DECLARE
    d TIMESTAMPTZ;
BEGIN
    SELECT debut INTO d FROM gold.alerte
    WHERE id_site = 'SITE-M' AND source = 'modele' AND fin IS null;
    ASSERT d = date_trunc('hour', now()) - INTERVAL '1 hour',
    format('début %s : il devait rester', d);
    RAISE NOTICE 'OK 2 : début atteint gardé';
END
$$;

-- 3. Une deuxième alerte en cours du modèle pour le même site est refusée
DO $$
BEGIN
    BEGIN
        INSERT INTO gold.alerte (id_site, source, type, severite, debut)
        VALUES ('SITE-M', 'modele', 'predicted_peak', 'high', now());
        RAISE EXCEPTION 'une deuxième alerte en cours devrait être refusée';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'OK 3 : une seule alerte du modèle en cours par site';
    END;
END
$$;

-- 4. Plus de pic : terminée maintenant. Puis un pic prévu dans 3 h et annulé :
-- ni fin ni début dans le futur
SELECT pg_temp.terminer(ARRAY['SITE-M']::VARCHAR[]);

SELECT pg_temp.ecrire_pic(
    'high', date_trunc('hour', now()) + INTERVAL '3 hours', 460,
    date_trunc('hour', now()) + INTERVAL '3 hours'
);
SELECT pg_temp.terminer(ARRAY['SITE-M']::VARCHAR[]);

DO $$
DECLARE
    n_en_cours INTEGER;
    n_futures INTEGER;
    n_terminees INTEGER;
BEGIN
    SELECT
        count(*) FILTER (WHERE fin IS null),
        count(*) FILTER (WHERE fin > now() OR debut > now()),
        count(*) FILTER (WHERE fin IS NOT null)
    INTO n_en_cours, n_futures, n_terminees
    FROM gold.alerte
    WHERE id_site = 'SITE-M' AND source = 'modele';
    ASSERT n_en_cours = 0 AND n_terminees = 2,
    format('%s en cours, %s terminées', n_en_cours, n_terminees);
    ASSERT n_futures = 0, format('%s alertes avec une date future', n_futures);
    RAISE NOTICE 'OK 4 : alertes terminées maintenant, aucune date future';
END
$$;

-- 5. Site plus évalué : son alerte est gardée jusqu'à la fin de l'heure de son
-- pic, puis terminée même sans être nommée
SELECT pg_temp.ecrire_pic(
    'high', date_trunc('hour', now()) - INTERVAL '3 hours', 460,
    date_trunc('hour', now()) - INTERVAL '2 hours'
);
SELECT pg_temp.terminer(ARRAY[]::VARCHAR[]);

DO $$
DECLARE
    n INTEGER;
BEGIN
    SELECT count(*) INTO n FROM gold.alerte
    WHERE id_site = 'SITE-M' AND source = 'modele' AND fin IS null;
    ASSERT n = 0, 'une alerte au pic passé devait être terminée';
    RAISE NOTICE 'OK 5 : alerte au pic passé terminée';
END
$$;

RESET ROLE;

-- 6. Les alertes de l'ETL ne sont pas concernées par l'index du modèle
INSERT INTO gold.alerte (id_site, source, type, severite, debut)
VALUES
('SITE-M', 'etl', 'threshold', 'high', '2026-10-29 08:00+00'),
('SITE-M', 'etl', 'threshold', 'high', '2026-10-29 09:00+00');

DO $$
BEGIN
    RAISE NOTICE 'OK 6 : plusieurs alertes ETL en cours restent possibles';
END
$$;

ROLLBACK;
