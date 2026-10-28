// Données de démonstration, reprises du wireframe Confluence (7 sites).
// À remplacer par les appels à l'API quand les routes existeront.

import type {
  FleetKpis,
  FleetTrend,
  PredictionPoint,
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
    // Capteur de consommation en panne (alerte ALR-2) : pas de mesure, comme dans l'API Mock
    consommationKw: null,
    picPrevu: null,
    qualite: { statut: 'partielle', heuresManquantes: 2 },
  },
  { site: site('SITE004'), consommationKw: 760, picPrevu: null, qualite: { statut: 'bonne' } },
  { site: site('SITE005'), consommationKw: 420, picPrevu: null, qualite: { statut: 'bonne' } },
  { site: site('SITE006'), consommationKw: 380, picPrevu: null, qualite: { statut: 'bonne' } },
  { site: site('SITE007'), consommationKw: 320, picPrevu: null, qualite: { statut: 'bonne' } },
]

export const kpis: FleetKpis = {
  // Total des 6 sites mesurés : SITE003 n'a pas de mesure
  consommationKw: 3840,
  nbSites: 7,
  nbSitesSansMesure: 1,
  coutJourEur: 6140,
  variationCoutPct: 4,
  co2JourTonnes: 2.1,
}

// Alertes : mocks/alertes.ts, au format de l'API

// Recommandations : mocks/recommandations.ts, au format de l'API

// Hypothèses de calcul en attendant les vraies valeurs (tarif du contrat, facteurs ADEME)
const TARIF_EUR_KWH = 0.18
const FACTEUR_CO2_KG_KWH = 0.052

/** Coût et CO₂ d'un site sur les 7 derniers jours */
export function siteCosts(siteId: string) {
  const kwh = siteSeries(siteId, 7 * 24).mesures.reduce((total, m) => total + (m.kw ?? 0), 0)
  return { coutEur: kwh * TARIF_EUR_KWH, co2Tonnes: (kwh * FACTEUR_CO2_KG_KWH) / 1000 }
}

/**
 * Évolution du parc, cohérente avec les KPI : la courbe de consommation suit la forme des
 * courbes des sites mesurés, ramenée pour finir sur la consommation actuelle du KPI ; le coût
 * finit sur le coût du jour, et la veille respecte la variation « vs hier ».
 */
export function fleetTrend(): FleetTrend {
  const measured = overview.filter((o) => o.consommationKw !== null)
  const hourly = measured.map((o) => siteSeries(o.site.id, 24).mesures)
  const shape = hourly[0]!.map((_, i) => hourly.reduce((total, m) => total + (m[i]!.kw ?? 0), 0))
  const scale = kpis.consommationKw / shape[shape.length - 1]!
  const consommationKw24h = shape.map((kw) => Math.round(kw * scale))

  const today = kpis.coutJourEur
  const yesterday = today / (1 + kpis.variationCoutPct / 100)
  // Jours précédents : variations de démonstration autour de la veille
  const earlier = [0.97, 1.03, 0.92, 0.99, 1.05].map((f) => yesterday * f)
  const coutEurJours7 = [...earlier, yesterday, today].map(Math.round)

  return { consommationKw24h, coutEurJours7 }
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

  // Comme l'API : de l'heure qui suit jusqu'à l'horizon, égal à la période affichée
  const predictions: PredictionPoint[] = Array.from({ length: historyHours }, (_, i) => {
    const date = at(i + 1)
    const kw = Math.round(daily(date))
    // La fourchette s'élargit avec l'horizon de prédiction
    const spread = kw * (0.02 + i * 0.0006)
    return {
      horodatage: date.toISOString(),
      kw,
      basseKw: Math.round(kw - spread * 1.8),
      hauteKw: Math.round(kw + spread),
      // Le maximum de l'heure n'est pas simulé : la page prend alors la moyenne horaire
      picKw: null,
      picBasKw: null,
      picHautKw: null,
      // Comme le modèle, au seuil d'alerte par défaut (90 %)
      picPrevu: kw >= capacity * 0.9,
    }
  })

  return { mesures, predictions }
}
