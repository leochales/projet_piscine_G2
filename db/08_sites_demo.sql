-- =============================================================================
-- EnerVision : initialisation de l'entrepôt de données
-- 08 : client et sites de démonstration
--
-- Les 7 sites de l'API Mock (GET /api/v1/sites), rattachés au client
-- « Démo EnerVision ». Le référentiel des sites appartient à l'application :
-- l'ETL ne fait que le lire (voir 06_roles.sql). En attendant l'écran
-- d'administration, ce script déclare les sites à collecter.
--
-- Exécuté au premier démarrage du conteneur PostgreSQL. Rejouable sans
-- effet sur une base existante (ON CONFLICT DO NOTHING).
-- =============================================================================

BEGIN;

INSERT INTO app.client (nom)
VALUES ('Démo EnerVision')
ON CONFLICT (nom) DO NOTHING;

INSERT INTO app.site (
    id_site, id_client, nom, type, localisation, capacite_kw
)
SELECT
    s.id_site,
    c.id_client,
    s.nom,
    s.type,
    s.localisation,
    s.capacite_kw
FROM (
    VALUES
    ('SITE001', 'Bureau Paris La Défense', 'office', 'Paris, France', 200.0),
    ('SITE002', 'Usine Lyon Vénissieux', 'factory', 'Lyon, France', 1000.0),
    (
        'SITE003', 'Data Center Marseille', 'datacenter', 'Marseille, France',
        800.0
    ),
    ('SITE004', 'Centre Commercial Lille', 'retail', 'Lille, France', 400.0),
    (
        'SITE005', 'Hôpital Toulouse Purpan', 'hospital', 'Toulouse, France',
        600.0
    ),
    ('SITE006', 'Bureau Bordeaux Centre', 'office', 'Bordeaux, France', 180.0),
    ('SITE007', 'Usine Nantes Rezé', 'factory', 'Nantes, France', 950.0)
) AS s (id_site, nom, type, localisation, capacite_kw)
CROSS JOIN app.client AS c
WHERE c.nom = 'Démo EnerVision'
ON CONFLICT (id_site) DO NOTHING;

COMMIT;
