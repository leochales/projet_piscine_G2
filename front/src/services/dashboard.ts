// Point d'accès unique aux données du dashboard.
// Les vues n'importent que ce fichier : brancher l'API ne changera que lui.

import * as mocks from '@/mocks/data'
import { recommandations as mockRecommandations } from '@/mocks/recommandations'
import {
  fleetFrom,
  kpisFrom,
  parisMidnight,
  costsFrom,
  toConsumptionPoint,
  toSiteOverview,
} from '@/lib/mesures'
import { toRecommendation } from '@/lib/recommendations'
import { getJson } from '@/services/http'
import type { ConsommationHoraireApi, DerniereMesureApi, RecommandationApi } from '@/types/api'
import type {
  Alert,
  FleetKpis,
  FleetTrend,
  Recommendation,
  SiteOverview,
  SiteSeries,
} from '@/types/energy'

/**
 * Source de chaque donnée : 'mock' (données simulées) ou 'api' (vraie route).
 * Les données simulées ont le format exact de la route : passer à 'api' ne change rien d'autre.
 */
export const SOURCES: Record<'recommandations' | 'mesures', 'mock' | 'api'> = {
  // GET /api/recommandations (SMARTOPS-39). À passer à 'api' une fois gold.recommandation
  // rempli par l'ETL (SMARTOPS-40)
  recommandations: 'mock',
  // GET /api/sites/derniere-mesure et /api/sites/{id}/consommation (SMARTOPS-42)
  mesures: 'api',
}

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

const HOUR_MS = 3600 * 1000

async function fetchDernieresMesures(): Promise<SiteOverview[]> {
  const lignes = await getJson<DerniereMesureApi[]>('/sites/derniere-mesure')
  return lignes.map(toSiteOverview)
}

async function fetchConsommation(siteId: string, debut: string): Promise<ConsommationHoraireApi[]> {
  return getJson<ConsommationHoraireApi[]>(`/sites/${encodeURIComponent(siteId)}/consommation`, {
    debut,
  })
}

/** Consommation horaire de chaque site du périmètre, depuis `debut` */
async function fetchConsommationDuParc(
  sites: readonly SiteOverview[],
  debut: string,
): Promise<ConsommationHoraireApi[]> {
  const series = await Promise.all(sites.map((site) => fetchConsommation(site.site.id, debut)))
  return series.flat()
}

export async function fetchKpis(): Promise<FleetKpis> {
  if (SOURCES.mesures !== 'api') return respond(mocks.kpis)
  const sites = await fetchDernieresMesures()
  const heures = await fetchConsommationDuParc(sites, parisMidnight(-1).toISOString())
  return kpisFrom(sites, heures)
}

export async function fetchOverview(): Promise<SiteOverview[]> {
  if (SOURCES.mesures !== 'api') return respond(mocks.overview, [])
  return fetchDernieresMesures()
}

export async function fetchFleetTrend(): Promise<FleetTrend> {
  if (SOURCES.mesures !== 'api')
    return respond(mocks.fleetTrend(), { consommationKw24h: [], coutEurJours7: [] })
  const sites = await fetchDernieresMesures()
  const heures = await fetchConsommationDuParc(sites, parisMidnight(-6).toISOString())
  return fleetFrom(heures)
}

export async function fetchSiteOverview(siteId: string): Promise<SiteOverview | undefined> {
  if (SOURCES.mesures !== 'api') return respond(mocks.overview.find((o) => o.site.id === siteId))
  const sites = await fetchDernieresMesures()
  return sites.find((site) => site.site.id === siteId)
}

export async function fetchSiteSeries(siteId: string, range: SeriesRange): Promise<SiteSeries> {
  if (SOURCES.mesures !== 'api') {
    return respond(mocks.siteSeries(siteId, range === '24h' ? 24 : 7 * 24), {
      mesures: [],
      predictions: [],
    })
  }
  const heures = range === '24h' ? 24 : 7 * 24
  const debut = new Date(Date.now() - heures * HOUR_MS).toISOString()
  const lignes = await fetchConsommation(siteId, debut)
  return {
    mesures: lignes.flatMap((ligne) => {
      const point = toConsumptionPoint(ligne)
      return point ? [point] : []
    }),
    // Prévisions : US2. On ne mélange pas une prévision simulée avec des mesures réelles.
    predictions: [],
  }
}

export async function fetchSiteCosts(siteId: string) {
  if (SOURCES.mesures !== 'api') return respond(mocks.siteCosts(siteId))
  const lignes = await fetchConsommation(siteId, parisMidnight(-6).toISOString())
  return costsFrom(lignes)
}

export const fetchAlerts = (): Promise<Alert[]> => respond(structuredClone(mocks.alerts), [])

// Recommandations en cours : à décider, ou acceptées (en cours d'application)
const STATUTS_EN_COURS = ['proposee', 'acceptee'] as const

/**
 * Recommandations en cours de tous les sites : l'écran 3 et la page d'un site les partagent
 * (store). Les refusées ne sont pas chargées.
 *
 * Avec l'API, une requête par statut : la route renvoie au plus 500 lignes, les plus récentes
 * d'abord, et les recommandations acceptées ou refusées s'accumulent. Une seule requête finirait
 * par écarter les propositions les plus anciennes, encore à décider.
 */
export async function fetchRecommendations(): Promise<Recommendation[]> {
  const reponse =
    SOURCES.recommandations === 'api'
      ? (
          await Promise.all(
            STATUTS_EN_COURS.map((statut) =>
              getJson<RecommandationApi[]>('/recommandations', { statut, limite: 500 }),
            ),
          )
        ).flat()
      : await respond(
          structuredClone(mockRecommandations).filter((r) =>
            (STATUTS_EN_COURS as readonly string[]).includes(r.statut),
          ),
          [],
        )
  return reponse.map(toRecommendation)
}

export const fetchPreviousSavings = (): Promise<number> => respond(mocks.economiesAnterieuresEur)

// Actions de l'écran 3. Simulées : l'API n'a pas encore de route pour les enregistrer (US7).
// Elles échouent avec ?simulation=erreur, comme le feraient les vraies routes.
export const acknowledgeAlert = (alertId: string): Promise<string> => respond(alertId)

/**
 * Décider d'une recommandation n'est possible qu'avec les données simulées : avec les vraies
 * recommandations, une décision simulée serait annoncée comme faite sans être enregistrée.
 * À ouvrir avec la route d'enregistrement des décisions (US7, SMARTOPS-59).
 */
export const canDecideRecommendations = () => SOURCES.recommandations === 'mock'

export function decideRecommendation(
  id: string,
  statut: 'acceptee' | 'refusee',
): Promise<{ id: string; statut: 'acceptee' | 'refusee' }> {
  if (!canDecideRecommendations()) {
    return Promise.reject(new Error('Pas encore de route pour enregistrer la décision (US7)'))
  }
  return respond({ id, statut })
}
