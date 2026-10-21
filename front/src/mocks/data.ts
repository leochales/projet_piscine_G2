// Données de démonstration, reprises du wireframe Confluence (7 sites).
// À remplacer par les appels à l'API quand les routes existeront.

import type {
  Alert,
  FleetKpis,
  PredictionPoint,
  Recommendation,
  Site,
  SiteOverview,
  SiteSeries,
} from '@/types/energy'

export const sites: Site[] = [
  { id: 'SITE001', nom: 'Siège de Paris', type: 'bureaux', capaciteKw: 750 },
  { id: 'SITE002', nom: 'Usine de Lyon', type: 'usine', capaciteKw: 1900 },
  { id: 'SITE003', nom: 'Data center de Lille', type: 'data_center', capaciteKw: 1360 },
  { id: 'SITE004', nom: 'Hôpital de Nantes', type: 'hopital', capaciteKw: 1250 },
  { id: 'SITE005', nom: 'Entrepôt de Rennes', type: 'entrepot', capaciteKw: 800 },
  { id: 'SITE006', nom: 'Bureaux de Bordeaux', type: 'bureaux', capaciteKw: 600 },
  { id: 'SITE007', nom: 'Laboratoire de Grenoble', type: 'laboratoire', capaciteKw: 700 },
]

const site = (id: string) => sites.find((s) => s.id === id)!

function tomorrowAt(hour: number) {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(hour, 0, 0, 0)
  return d.toISOString()
}

export const overview: SiteOverview[] = [
  { site: site('SITE001'), consommationKw: 320, picPrevu: null, qualite: { statut: 'bonne' } },
  {
    site: site('SITE002'),
    consommationKw: 1640,
    picPrevu: { horodatage: tomorrowAt(14), pourcentageCapacite: 94 },
    qualite: { statut: 'bonne' },
  },
  {
    site: site('SITE003'),
    consommationKw: 980,
    picPrevu: null,
    qualite: { statut: 'partielle', heuresManquantes: 2 },
  },
  { site: site('SITE004'), consommationKw: 760, picPrevu: null, qualite: { statut: 'bonne' } },
  { site: site('SITE005'), consommationKw: 420, picPrevu: null, qualite: { statut: 'bonne' } },
  { site: site('SITE006'), consommationKw: 380, picPrevu: null, qualite: { statut: 'bonne' } },
  { site: site('SITE007'), consommationKw: 320, picPrevu: null, qualite: { statut: 'bonne' } },
]

export const kpis: FleetKpis = {
  consommationKw: 4820,
  nbSites: 7,
  coutJourEur: 6140,
  variationCoutPct: 4,
  co2JourTonnes: 2.1,
}

export const alerts: Alert[] = [
  {
    id: 'ALR-1',
    siteId: 'SITE002',
    gravite: 'critique',
    message: 'Pic prévu à 94 % de la capacité, demain 14 h',
    priseEnCompte: false,
  },
  {
    id: 'ALR-2',
    siteId: 'SITE003',
    gravite: 'moyenne',
    message: 'Capteur en panne depuis 2 h',
    priseEnCompte: false,
  },
  {
    id: 'ALR-3',
    siteId: 'SITE006',
    gravite: 'faible',
    message: 'Consommation inhabituelle la nuit',
    priseEnCompte: false,
  },
]

export const recommendations: Recommendation[] = [
  {
    id: 'REC-1',
    siteId: 'SITE002',
    titre: 'Décaler la ligne de production B de 14 h à 20 h',
    alerteLiee: 'pic prévu',
    gainEstimeEur: 380,
    periodeGain: 'ponctuel',
    statut: 'proposee',
  },
  {
    id: 'REC-2',
    siteId: 'SITE006',
    titre: "Programmer l'arrêt de la climatisation à 22 h",
    alerteLiee: null,
    gainEstimeEur: 45,
    periodeGain: 'semaine',
    statut: 'proposee',
  },
]

// Hypothèses de calcul en attendant les vraies valeurs (tarif du contrat, facteurs ADEME)
const TARIF_EUR_KWH = 0.18
const FACTEUR_CO2_KG_KWH = 0.052

/** Coût et CO₂ d'un site sur les 7 derniers jours */
export function siteCosts(siteId: string) {
  const kwh = siteSeries(siteId, 7 * 24).mesures.reduce((total, m) => total + m.kw, 0)
  return { coutEur: kwh * TARIF_EUR_KWH, co2Tonnes: (kwh * FACTEUR_CO2_KG_KWH) / 1000 }
}

/** Économies déjà réalisées ce mois-ci, avant les recommandations affichées */
export const economiesAnterieuresEur = 1250

/**
 * Courbe journalière : pic à 14 h (~82 % de la capacité), creux la nuit.
 * Un site avec un pic prévu (SITE002) a en plus une bosse demain 14 h,
 * pour atteindre la valeur du tableau (~94 %, soit ~1 790 kW), comme dans le wireframe.
 */
export function siteSeries(siteId: string, historyHours: number): SiteSeries {
  const current = overview.find((o) => o.site.id === siteId)
  const capacity = current?.site.capaciteKw ?? 1000
  const base = capacity * 0.62
  const amplitude = capacity * 0.2
  const peak = current?.picPrevu
  const bump = peak ? capacity * (peak.pourcentageCapacite / 100 - 0.82) : 0
  const peakTime = peak ? new Date(peak.horodatage).getTime() : 0

  const now = new Date()
  now.setMinutes(0, 0, 0)
  const at = (offsetHours: number) => new Date(now.getTime() + offsetHours * 3_600_000)
  const daily = (date: Date) => {
    const hoursFromPeak = (date.getTime() - peakTime) / 3_600_000
    return (
      base +
      amplitude * Math.cos(((date.getHours() - 14) / 24) * 2 * Math.PI) +
      bump * Math.exp(-(hoursFromPeak ** 2) / (2 * 4 ** 2))
    )
  }

  const mesures = Array.from({ length: historyHours + 1 }, (_, i) => {
    const date = at(i - historyHours)
    // Bruit déterministe : la courbe ne change pas à chaque rechargement
    const noise = Math.sin(i * 1.7) * capacity * 0.03
    return { horodatage: date.toISOString(), kw: Math.round(daily(date) + noise) }
  })

  const predictions: PredictionPoint[] = Array.from({ length: 49 }, (_, i) => {
    const date = at(i)
    const kw = Math.round(daily(date))
    // La fourchette s'élargit avec l'horizon de prédiction
    const spread = kw * (0.02 + i * 0.0006)
    return {
      horodatage: date.toISOString(),
      kw,
      basseKw: Math.round(kw - spread * 1.8),
      hauteKw: Math.round(kw + spread),
    }
  })

  return { mesures, predictions }
}
