// Alertes simulées, au format exact de GET /api/alertes : quand la route sera branchée
// (services/dashboard.ts, SOURCES), le dashboard recevra les mêmes champs.
// Seuil d'alerte d'un site : 90 % de sa capacité (lib/indicators.ts, SEUIL_ALERTE_PCT).

import type { AlerteApi } from '@/types/api'

// Dates relatives à maintenant : toujours dans le passé, quelle que soit l'heure de la démo
const HOUR_MS = 3600 * 1000
const hoursAgo = (hours: number) => new Date(Date.now() - hours * HOUR_MS).toISOString()

const ENCOURS = { fin: null, prise_en_compte: false, prise_par: null, prise_le: null }

export const alertes: AlerteApi[] = [
  {
    id_alerte: 1,
    id_site: 'SITE002',
    nom_site: 'Usine de Lyon',
    source: 'modele',
    type: 'predicted_peak',
    severite: 'critical',
    message: 'Pic prévu à 94 % de la capacité, demain 14 h',
    debut: hoursAgo(1),
    valeur: null,
    seuil: null,
    ...ENCOURS,
  },
  // US3 : la consommation mesurée du site a dépassé son seuil d'alerte
  {
    id_alerte: 5,
    id_site: 'SITE005',
    nom_site: 'Entrepôt de Rennes',
    source: 'etl',
    type: 'threshold',
    severite: 'high',
    message: null,
    debut: hoursAgo(0.5),
    valeur: 752,
    seuil: 720, // 90 % de 800 kW
    ...ENCOURS,
  },
  {
    id_alerte: 2,
    id_site: 'SITE003',
    nom_site: 'Data center de Lille',
    source: 'api_mock',
    type: 'sensor',
    severite: 'medium',
    message: 'Capteur en panne depuis 2 h',
    debut: hoursAgo(2),
    valeur: null,
    seuil: null,
    ...ENCOURS,
  },
  {
    id_alerte: 3,
    id_site: 'SITE006',
    nom_site: 'Bureaux de Bordeaux',
    source: 'etl',
    type: 'anomaly',
    severite: 'low',
    message: 'Consommation inhabituelle la nuit',
    debut: hoursAgo(6),
    valeur: null,
    seuil: null,
    ...ENCOURS,
  },
  // Déjà prise en compte par une autre personne : l'API donne son identifiant, pas son nom
  {
    id_alerte: 4,
    id_site: 'SITE004',
    nom_site: 'Hôpital de Nantes',
    source: 'etl',
    type: 'threshold',
    severite: 'medium',
    message: null,
    debut: hoursAgo(20),
    valeur: 1140,
    seuil: 1125, // 90 % de 1 250 kW
    fin: null,
    prise_en_compte: true,
    prise_par: '3f1c2a9e-7b4d-4e21-9c55-2d6b8a0f1e77',
    prise_le: hoursAgo(19),
  },
]
