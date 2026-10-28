-- =============================================================================
-- Tests des alertes de pic prévu du modèle (db/19_alerte_modele.sql) : une
-- seule alerte en cours par site, mise à jour par INSERT ... ON CONFLICT
-- (model/alerte_pic.py), avec les droits du compte model
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

SET ROLE model;

-- 1. Première alerte en cours, comme l'écrit model/alerte_pic.py
INSERT INTO gold.alerte (
    id_site, source, type, severite, debut, valeur, valeur_le, seuil
)
VALUES (
    'SITE-M', 'modele', 'predicted_peak', 'high',
    '2026-10-29 14:00+00', 460, '2026-10-29 15:00+00', 450
)
ON CONFLICT (id_site, type)
WHERE source = 'modele' AND fin IS null
DO UPDATE SET
    severite = excluded.severite,
    valeur = excluded.valeur,
    valeur_le = excluded.valeur_le,
    seuil = excluded.seuil,
    debut = least(gold.alerte.debut, excluded.debut);

-- 2. Passage suivant : même alerte mise à jour, début gardé s'il est plus tôt
INSERT INTO gold.alerte (
    id_site, source, type, severite, debut, valeur, valeur_le, seuil
)
VALUES (
    'SITE-M', 'modele', 'predicted_peak', 'critical',
    '2026-10-29 16:00+00', 560, '2026-10-29 17:00+00', 450
)
ON CONFLICT (id_site, type)
WHERE source = 'modele' AND fin IS null
DO UPDATE SET
    severite = excluded.severite,
    valeur = excluded.valeur,
    valeur_le = excluded.valeur_le,
    seuil = excluded.seuil,
    debut = least(gold.alerte.debut, excluded.debut);

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
    ASSERT a.valeur_le = '2026-10-29 17:00+00', format('valeur_le %s', a.valeur_le);
    ASSERT a.debut = '2026-10-29 14:00+00', format('début %s', a.debut);
    RAISE NOTICE 'OK 1-2 : alerte créée puis mise à jour, sans doublon';
END
$$;

-- 3. Une deuxième alerte en cours du modèle pour le même site est refusée
DO $$
BEGIN
    BEGIN
        INSERT INTO gold.alerte (id_site, source, type, severite, debut)
        VALUES (
            'SITE-M', 'modele', 'predicted_peak', 'high',
            '2026-10-30 10:00+00'
        );
        RAISE EXCEPTION 'une deuxième alerte en cours devrait être refusée';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'OK 3 : une seule alerte du modèle en cours par site';
    END;
END
$$;

-- 4. Terminée, comme model/alerte_pic.py le fait (début encore à venir : la
-- fin prend le début), puis une nouvelle alerte peut s'ouvrir
UPDATE gold.alerte
SET fin = greatest(debut, now())
WHERE
    source = 'modele'
    AND type = 'predicted_peak'
    AND fin IS null
    AND id_site = any(ARRAY['SITE-M']);

INSERT INTO gold.alerte (id_site, source, type, severite, debut)
VALUES ('SITE-M', 'modele', 'predicted_peak', 'high', '2026-10-30 10:00+00');

DO $$
DECLARE
    n_en_cours INTEGER;
    n_terminees INTEGER;
BEGIN
    SELECT
        count(*) FILTER (WHERE fin IS null),
        count(*) FILTER (WHERE fin IS NOT null)
    INTO n_en_cours, n_terminees
    FROM gold.alerte
    WHERE id_site = 'SITE-M' AND source = 'modele';
    ASSERT n_en_cours = 1 AND n_terminees = 1,
    format('%s en cours, %s terminées', n_en_cours, n_terminees);
    RAISE NOTICE 'OK 4 : alerte terminée gardée, nouvelle alerte ouverte';
END
$$;

RESET ROLE;

-- 5. Les alertes de l'ETL ne sont pas concernées par l'index du modèle
INSERT INTO gold.alerte (id_site, source, type, severite, debut)
VALUES
('SITE-M', 'etl', 'threshold', 'high', '2026-10-29 08:00+00'),
('SITE-M', 'etl', 'threshold', 'high', '2026-10-29 09:00+00');

DO $$
BEGIN
    RAISE NOTICE 'OK 5 : plusieurs alertes ETL en cours restent possibles';
END
$$;

ROLLBACK;
