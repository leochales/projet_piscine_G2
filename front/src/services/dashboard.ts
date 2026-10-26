// Point d'accès unique aux données du dashboard.
// Les vues n'importent que ce fichier : brancher l'API ne changera que lui.

import * as mocks from '@/mocks/data'
import { alertes as mockAlertes } from '@/mocks/alertes'
import { recommandations as mockRecommandations } from '@/mocks/recommandations'
import { toAlert } from '@/lib/alerts'
import { toRecommendation } from '@/lib/recommendations'
import { getJson } from '@/services/http'
import type { AlerteApi, RecommandationApi } from '@/types/api'
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
export const SOURCES: Record<'recommandations' | 'alertes', 'mock' | 'api'> = {
  // GET /api/recommandations (SMARTOPS-39). À passer à 'api' une fois les jetons envoyés
  // par le front (SMARTOPS-85) et gold.recommandation rempli par l'ETL (SMARTOPS-40)
  recommandations: 'mock',
  // GET /api/alertes (SMARTOPS-39). À passer à 'api' une fois gold.alerte rempli par l'ETL
  // (dépassements de seuil et pics, SMARTOPS-26)
  alertes: 'mock',
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

/** Alertes en cours de tous les sites : l'écran 3, l'en-tête et la page d'un site les partagent */
export async function fetchAlerts(): Promise<Alert[]> {
  const reponse =
    SOURCES.alertes === 'api'
      ? await getJson<AlerteApi[]>('/alertes', { en_cours: true, limite: 500 })
      : await respond(structuredClone(mockAlertes), [])
  return reponse.map(toAlert)
}

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

/**
 * Prendre une alerte en compte n'est possible qu'avec les données simulées : avec les vraies
 * alertes, une prise en compte simulée serait annoncée comme faite sans être enregistrée.
 * À ouvrir avec la route d'enregistrement (US7, SMARTOPS-59).
 */
export const canAcknowledgeAlerts = () => SOURCES.alertes === 'mock'

export function acknowledgeAlert(alertId: string): Promise<string> {
  if (!canAcknowledgeAlerts()) {
    return Promise.reject(new Error('Pas encore de route pour prendre une alerte en compte (US7)'))
  }
  return respond(alertId)
}

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
