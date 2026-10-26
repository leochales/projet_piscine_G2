// Recommandations simulées, au format exact de GET /api/recommandations : quand la route
// sera branchée (services/dashboard.ts, SOURCES), le dashboard recevra les mêmes champs.

import type { RecommandationApi } from '@/types/api'

// Dates relatives à maintenant : toujours dans le passé, quelle que soit l'heure de la démo
const HOUR_MS = 3600 * 1000
const hoursAgo = (hours: number) => new Date(Date.now() - hours * HOUR_MS).toISOString()
const daysAgo = (days: number) => hoursAgo(days * 24)

export const recommandations: RecommandationApi[] = [
  {
    id_recommandation: 1,
    id_site: 'SITE002',
    nom_site: 'Usine de Lyon',
    id_alerte: 1,
    regle: 'pic_prevu',
    titre: 'Décaler la ligne de production B de 14 h à 20 h',
    description: 'Le pic prévu dans les prochaines heures dépasse 90 % de la capacité du site.',
    date_creation: hoursAgo(2),
    gain_estime_eur: 380,
    periode_gain: 'unique',
    statut: 'proposee',
    decide_par: null,
    decide_le: null,
  },
  {
    id_recommandation: 2,
    id_site: 'SITE002',
    nom_site: 'Usine de Lyon',
    id_alerte: null,
    regle: 'veille_nuit',
    titre: 'Couper les compresseurs d’air la nuit',
    description: 'La consommation reste au-dessus de 30 % de la capacité entre 23 h et 5 h.',
    date_creation: daysAgo(2),
    gain_estime_eur: 120,
    periode_gain: 'semaine',
    statut: 'acceptee',
    decide_par: '8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10',
    decide_le: daysAgo(1),
  },
  {
    id_recommandation: 3,
    id_site: 'SITE002',
    nom_site: 'Usine de Lyon',
    id_alerte: null,
    regle: 'eclairage',
    titre: 'Passer l’éclairage de l’entrepôt en détection de présence',
    description: null,
    date_creation: daysAgo(6),
    gain_estime_eur: 60,
    periode_gain: 'semaine',
    statut: 'refusee',
    decide_par: '8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10',
    decide_le: daysAgo(5),
  },
  {
    id_recommandation: 4,
    id_site: 'SITE006',
    nom_site: 'Bureaux de Bordeaux',
    id_alerte: null,
    regle: 'climatisation',
    titre: 'Programmer l’arrêt de la climatisation à 22 h',
    description: 'La climatisation tourne toute la nuit alors que le bâtiment est vide.',
    date_creation: hoursAgo(3),
    gain_estime_eur: 45,
    periode_gain: 'semaine',
    statut: 'proposee',
    decide_par: null,
    decide_le: null,
  },
  // Gain pas encore estimé par la règle : affiché sans montant
  {
    id_recommandation: 5,
    id_site: 'SITE003',
    nom_site: 'Data center de Lille',
    id_alerte: null,
    regle: 'refroidissement',
    titre: 'Relever la consigne de refroidissement de 2 °C',
    description: 'La température des salles reste sous la plage recommandée.',
    date_creation: daysAgo(1),
    gain_estime_eur: null,
    periode_gain: null,
    statut: 'proposee',
    decide_par: null,
    decide_le: null,
  },
]
