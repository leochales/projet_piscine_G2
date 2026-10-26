// Point d'accès unique aux données du dashboard.
// Les vues n'importent que ce fichier : brancher l'API ne changera que lui.

import * as mocks from '@/mocks/data'
import type {
  Alert,
  FleetKpis,
  FleetTrend,
  Recommendation,
  SiteOverview,
  SiteSeries,
} from '@/types/energy'

export type SeriesRange = '24h' | '7j'

// Simulation des cas réels, en développement seulement, pour voir chaque état des écrans :
// ajouter ?simulation=lent, ?simulation=erreur ou ?simulation=vide à l'adresse.
export type Simulation = 'lent' | 'erreur' | 'vide'

const SIMULATIONS: readonly Simulation[] = ['lent', 'erreur', 'vide']
const DELAY_MS = 150
export const SLOW_DELAY_MS = 3000

export function readSimulation(
  search: string = window.location.search,
  dev: boolean = import.meta.env.DEV,
): Simulation | null {
  if (!dev) return null
  const value = new URLSearchParams(search).get('simulation')
  return SIMULATIONS.find((s) => s === value) ?? null
}

/** Réponse simulée ; `empty` est renvoyé avec ?simulation=vide (listes et courbes vides) */
function respond<T>(value: T, empty?: T): Promise<T> {
  const simulation = readSimulation()
  return new Promise<T>((resolve, reject) =>
    setTimeout(
      () => {
        if (simulation === 'erreur') reject(new Error('API simulée en erreur'))
        else resolve(simulation === 'vide' && empty !== undefined ? empty : value)
      },
      simulation === 'lent' ? SLOW_DELAY_MS : DELAY_MS,
    ),
  )
}

export const fetchKpis = (): Promise<FleetKpis> => respond(mocks.kpis)

export const fetchOverview = (): Promise<SiteOverview[]> => respond(mocks.overview, [])

export const fetchFleetTrend = (): Promise<FleetTrend> =>
  respond(mocks.fleetTrend(), { consommationKw24h: [], coutEurJours7: [] })

export const fetchSiteOverview = (siteId: string): Promise<SiteOverview | undefined> =>
  respond(mocks.overview.find((o) => o.site.id === siteId))

export const fetchSiteSeries = (siteId: string, range: SeriesRange): Promise<SiteSeries> =>
  respond(mocks.siteSeries(siteId, range === '24h' ? 24 : 7 * 24), {
    mesures: [],
    predictions: [],
  })

export const fetchSiteCosts = (siteId: string) => respond(mocks.siteCosts(siteId))

export const fetchAlerts = (): Promise<Alert[]> => respond(structuredClone(mocks.alerts), [])

export const fetchRecommendations = (): Promise<Recommendation[]> =>
  respond(structuredClone(mocks.recommendations), [])

export const fetchPreviousSavings = (): Promise<number> => respond(mocks.economiesAnterieuresEur)

// Actions de l'écran 3. Simulées : l'API n'a pas encore de route pour les enregistrer (US7).
// Elles échouent avec ?simulation=erreur, comme le feraient les vraies routes.
export const acknowledgeAlert = (alertId: string): Promise<string> => respond(alertId)

export const decideRecommendation = (
  id: string,
  statut: 'acceptee' | 'refusee',
): Promise<{ id: string; statut: 'acceptee' | 'refusee' }> => respond({ id, statut })
