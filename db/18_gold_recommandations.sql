-- =============================================================================
-- EnerVision : recommandations dans gold (SMARTOPS-40)
-- 18 : règles simples, appliquées par l'ETL aux alertes en cours.
--
-- Les recommandations ne viennent pas du modèle : chaque alerte en cours de
-- gold.alerte reçoit une recommandation, tirée de la règle qui correspond à son
-- type et à sa sévérité. En pratique, les alertes de l'ETL (threshold, sensor,
-- 17_gold_alertes.sql) et bientôt celles du modèle (predicted_peak) : celles de
-- l'API Mock ne sont pas reprises dans gold.alerte.
-- Rejouable sans effet (db/tools/migrate.sh).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Règles : une alerte prend la règle de même type et même sévérité, sinon
-- celle de son type (severite vide), sinon la règle générique (type et
-- severite vides)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.regle_recommandation (
    regle VARCHAR(50) PRIMARY KEY,
    type VARCHAR(20),  -- noqa: RF04
    severite VARCHAR(10),
    titre VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    -- Une seule règle par couple, cases vides comprises
    UNIQUE NULLS NOT DISTINCT (type, severite),
    -- Une règle générique n'a pas de sévérité
    CHECK (type IS NOT null OR severite IS null)
);

COMMENT ON TABLE gold.regle_recommandation IS
'Règles de recommandation par type et sévérité d''alerte '
'(cases vides = toutes)';

-- ON CONFLICT DO UPDATE : modifier un texte ici puis migrer met la règle à jour
INSERT INTO gold.regle_recommandation (
    regle, type, severite, titre, description
) VALUES
(
    'threshold_critical', 'threshold', 'critical',
    'Délestage d''urgence',
    'La consommation dépasse 110 % de la capacité du site. Couper les '
    || 'équipements non essentiels pour éviter un déclenchement du disjoncteur.'
),
(
    'threshold', 'threshold', null,
    'Réduire la charge',
    'La consommation dépasse le seuil d''alerte du site. Décaler ou arrêter '
    || 'les équipements non essentiels.'
),
(
    'spike_critical', 'spike', 'critical',
    'Pic critique : intervenir sur le site',
    'Pic de consommation critique. Couper les charges non essentielles et '
    || 'prévenir le responsable du site.'
),
(
    'spike', 'spike', null,
    'Analyser le pic de consommation',
    'Un pic anormal a été détecté. Identifier l''équipement en cause et '
    || 'vérifier son fonctionnement.'
),
(
    'predicted_peak', 'predicted_peak', null,
    'Anticiper le pic prévu',
    'Le modèle prévoit un dépassement du seuil du site. Décaler les usages '
    || 'non urgents avant l''heure prévue.'
),
(
    'anomaly', 'anomaly', null,
    'Diagnostiquer l''anomalie',
    'La consommation est inhabituelle. Vérifier les capteurs et les '
    || 'équipements qui tournent hors des horaires prévus.'
),
(
    'outage', 'outage', null,
    'Faire intervenir la maintenance',
    'Une coupure a été détectée. Contacter la maintenance et vérifier les '
    || 'protections électriques.'
),
(
    'sensor', 'sensor', null,
    'Vérifier le capteur',
    'Des mesures manquent ou sont incohérentes. Vérifier l''alimentation et '
    || 'la connexion du capteur.'
),
(
    'alerte_generique', null, null,
    'Examiner l''alerte',
    'Une alerte est en cours sur ce site. Examiner les mesures récentes.'
)
ON CONFLICT (regle) DO UPDATE SET
    type = excluded.type,
    severite = excluded.severite,
    titre = excluded.titre,
    description = excluded.description;

GRANT SELECT ON gold.regle_recommandation TO etl;

-- Une seule recommandation par alerte : deux passages de l'ETL en même temps
-- ne créent pas de doublon
CREATE UNIQUE INDEX IF NOT EXISTS idx_recommandation_alerte
ON gold.recommandation (id_alerte) WHERE id_alerte IS NOT null;


-- L'ETL lit les décisions pour savoir quelles recommandations sont encore
-- proposées : l'identifiant seulement, ni qui a décidé ni quand
GRANT SELECT (id_recommandation) ON app.decision_recommandation TO etl;


-- -----------------------------------------------------------------------------
-- Génération, appelée chaque minute par l'ETL (etl/recommandations.py)
--
-- Une recommandation par alerte en cours (fin vide) d'un site actif. Tant que
-- personne n'a décidé (pas de ligne dans app.decision_recommandation), elle
-- suit l'alerte : 17_gold_alertes.sql met à jour sa sévérité et sa valeur à
-- chaque minute, donc une alerte passée en critical prend la règle critical, et
-- son gain suit le maximum atteint. Une recommandation acceptée ou refusée ne
-- change plus : son texte et son gain restent ceux de la décision. Une alerte
-- terminée garde la sienne telle quelle.
--
-- Gain estimé (SMARTOPS-90), seulement pour les dépassements de seuil (types
-- threshold, spike et predicted_peak, valeur au-dessus du seuil) :
--   gain = (valeur - seuil) kW × 1 h × prix du kWh, période « unique »,
-- soit l'énergie évitée en ramenant la consommation au seuil pendant une heure.
-- La durée de l'alerte n'entre pas dans le calcul : une alerte de 10 minutes et
-- une alerte de 5 heures au même maximum ont le même gain (choix du MVP).
-- Pour les autres alertes, le gain n'est pas estimé (vide).
--
-- Exécutée avec les droits de l'appelant (compte etl).
-- Retourne le nombre de recommandations créées et mises à jour.
-- -----------------------------------------------------------------------------
-- Le type de retour a changé (BIGINT avant) : CREATE OR REPLACE ne peut pas
-- le modifier
DROP FUNCTION IF EXISTS gold.generer_recommandations(NUMERIC);

CREATE FUNCTION gold.generer_recommandations(prix_kwh_eur NUMERIC)
RETURNS TABLE (creees BIGINT, mises_a_jour BIGINT)
-- plpgsql : même raison que gold.calculer_consommation_horaire
-- (12_gold_horaire.sql)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH ecrites AS (
        INSERT INTO gold.recommandation AS rec (
            id_site, id_alerte, regle, titre, description,
            gain_estime_eur, periode_gain
        )
        SELECT
            a.id_site,
            a.id_alerte,
            r.regle,
            r.titre,
            r.description,
            g.gain,
            CASE WHEN g.gain IS NOT null THEN 'unique' END
        FROM gold.alerte AS a
        INNER JOIN app.site AS s ON a.id_site = s.id_site
        -- Règle la plus précise : même sévérité, puis même type, puis générique
        CROSS JOIN LATERAL (
            SELECT rr.regle, rr.titre, rr.description
            FROM gold.regle_recommandation AS rr
            WHERE (rr.type = a.type OR rr.type IS null)
              AND (rr.severite = a.severite OR rr.severite IS null)
            ORDER BY rr.type IS null, rr.severite IS null
            LIMIT 1
        ) AS r
        CROSS JOIN LATERAL (
            SELECT CASE
                WHEN a.type IN ('threshold', 'spike', 'predicted_peak')
                     AND a.valeur > a.seuil
                    THEN round((a.valeur - a.seuil) * prix_kwh_eur, 2)
            END AS gain
        ) AS g
        WHERE a.fin IS null
          AND s.statut = 'active'
        -- Déjà une recommandation : mise à jour si personne n'a décidé et si
        -- quelque chose a changé (sinon la ligne n'est pas réécrite)
        ON CONFLICT (id_alerte) WHERE id_alerte IS NOT null DO UPDATE SET
            regle = excluded.regle,
            titre = excluded.titre,
            description = excluded.description,
            gain_estime_eur = excluded.gain_estime_eur,
            periode_gain = excluded.periode_gain
        WHERE NOT EXISTS (
            SELECT 1 FROM app.decision_recommandation AS d
            WHERE d.id_recommandation = rec.id_recommandation
        )
        AND (
            rec.regle, rec.titre, rec.description,
            rec.gain_estime_eur, rec.periode_gain
        ) IS DISTINCT FROM (
            excluded.regle, excluded.titre, excluded.description,
            excluded.gain_estime_eur, excluded.periode_gain
        )
        -- old : la ligne avant l'écriture, vide pour une création (PostgreSQL 18)
        RETURNING old.id_recommandation IS null AS creee
    )

    SELECT
        count(*) FILTER (WHERE e.creee),
        count(*) FILTER (WHERE NOT e.creee)
    FROM ecrites AS e;
END;
$$;

REVOKE ALL ON FUNCTION gold.generer_recommandations(NUMERIC) FROM public;
GRANT EXECUTE ON FUNCTION gold.generer_recommandations(NUMERIC) TO etl;

COMMIT;
