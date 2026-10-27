// Point d'accès unique aux données du dashboard.
// Les vues n'importent que ce fichier : brancher l'API ne changera que lui.

import * as mocks from '@/mocks/data'
import { alertes as mockAlertes } from '@/mocks/alertes'
import { etats as mockEtats } from '@/mocks/etat'
import { recommandations as mockRecommandations } from '@/mocks/recommandations'
import { toAlert } from '@/lib/alerts'
import { toSiteStatus } from '@/lib/etat'
import {
  fleetFrom,
  kpisFrom,
  parisMidnight,
  costsFrom,
  toConsumptionPoint,
  toSiteOverview,
} from '@/lib/mesures'
import { toRecommendation } from '@/lib/recommendations'
import { getJson, postJson } from '@/services/http'
import type {
  AlerteApi,
  ConsommationHoraireApi,
  DerniereMesureApi,
  EtatSiteApi,
  RecommandationApi,
} from '@/types/api'
import type {
  Alert,
  FleetKpis,
  FleetTrend,
  Recommendation,
  SiteOverview,
  SiteSeries,
  SiteStatus,
} from '@/types/energy'

/**
 * Source de chaque donnée : 'mock' (données simulées) ou 'api' (vraie route).
 * Les données simulées ont le format exact de la route : passer à 'api' ne change rien d'autre.
 */
export const SOURCES: Record<'recommandations' | 'alertes' | 'mesures' | 'etat', 'mock' | 'api'> = {
  // GET /api/recommandations (SMARTOPS-39). À passer à 'api' une fois gold.recommandation
  // rempli par l'ETL (SMARTOPS-40)
  recommandations: 'mock',
  // GET /api/alertes (SMARTOPS-39) : gold.alerte, rempli par l'ETL (dépassements de seuil
  // et pannes de capteur, SMARTOPS-26)
  alertes: 'api',
  // GET /api/sites/derniere-mesure et /api/sites/{id}/consommation (SMARTOPS-42)
  mesures: 'api',
  // GET /api/sites/etat : transmission et capteurs (US4, vue gold.etat_site de SMARTOPS-23)
  etat: 'api',
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

/**
 * Même simulation pour un appel réseau. « erreur » et « vide » n'atteignent pas l'API :
 * on peut voir ces états sans que la route échoue ou se vide vraiment.
 */
async function fromApi<T>(load: () => Promise<T>, empty?: T): Promise<T> {
  const simulation = readSimulation()
  if (simulation === 'erreur') return respond(undefined as T)
  if (simulation === 'vide' && empty !== undefined) return respond(empty, empty)
  if (simulation === 'lent') await new Promise((resolve) => setTimeout(resolve, SLOW_DELAY_MS))
  return load()
}

/** Début de période aligné sur une heure UTC pleine, comme la borne `fin` de l'API. */
function debutAvant(heures: number, now = new Date()): string {
  const fin = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours())
  return new Date(fin - heures * HOUR_MS).toISOString()
}

const HOUR_MS = 3600 * 1000

// Appels en cours, partagés entre les requêtes lancées ensemble (KPI, liste, mini-courbes).
// Oubliés dès la réponse : le rafraîchissement suivant reprend des données neuves.
let dernieresEnCours: Promise<SiteOverview[]> | null = null
const consommationEnCours = new Map<string, Promise<ConsommationHoraireApi[]>>()

async function fetchDernieresMesures(): Promise<SiteOverview[]> {
  dernieresEnCours ??= getJson<DerniereMesureApi[]>('/sites/derniere-mesure')
    .then((lignes) => lignes.map(toSiteOverview))
    .finally(() => {
      dernieresEnCours = null
    })
  return dernieresEnCours
}

async function fetchConsommation(siteId: string, debut: string): Promise<ConsommationHoraireApi[]> {
  return getJson<ConsommationHoraireApi[]>(`/sites/${encodeURIComponent(siteId)}/consommation`, {
    debut,
  })
}

/** Consommation horaire de chaque site du périmètre, depuis `debut` */
function fetchConsommationDuParc(
  sites: readonly SiteOverview[],
  debut: string,
): Promise<ConsommationHoraireApi[]> {
  const cle = `${debut}|${sites.map((site) => site.site.id).join(',')}`
  const enCours = consommationEnCours.get(cle)
  if (enCours) return enCours
  const promesse = Promise.all(sites.map((site) => fetchConsommation(site.site.id, debut)))
    .then((series) => series.flat())
    .finally(() => {
      consommationEnCours.delete(cle)
    })
  consommationEnCours.set(cle, promesse)
  return promesse
}

// Sept jours : les KPI n'utilisent que hier et aujourd'hui, mais la même requête sert
// aux mini-courbes, lancées en même temps.
const DEBUT_PARC = () => parisMidnight(-6).toISOString()

export async function fetchKpis(): Promise<FleetKpis> {
  if (SOURCES.mesures !== 'api') return respond(mocks.kpis)
  return fromApi(async () => {
    const sites = await fetchDernieresMesures()
    const heures = await fetchConsommationDuParc(sites, DEBUT_PARC())
    return kpisFrom(sites, heures)
  })
}

export async function fetchOverview(): Promise<SiteOverview[]> {
  if (SOURCES.mesures !== 'api') return respond(mocks.overview, [])
  return fromApi(() => fetchDernieresMesures(), [])
}

export async function fetchFleetTrend(): Promise<FleetTrend> {
  if (SOURCES.mesures !== 'api')
    return respond(mocks.fleetTrend(), { consommationKw24h: [], coutEurJours7: [] })
  return fromApi(
    async () => {
      const sites = await fetchDernieresMesures()
      const heures = await fetchConsommationDuParc(sites, DEBUT_PARC())
      return fleetFrom(heures)
    },
    { consommationKw24h: [], coutEurJours7: [] },
  )
}

export async function fetchSiteOverview(siteId: string): Promise<SiteOverview | undefined> {
  if (SOURCES.mesures !== 'api') return respond(mocks.overview.find((o) => o.site.id === siteId))
  return fromApi(async () => {
    const sites = await fetchDernieresMesures()
    return sites.find((site) => site.site.id === siteId)
  })
}

export async function fetchSiteSeries(siteId: string, range: SeriesRange): Promise<SiteSeries> {
  if (SOURCES.mesures !== 'api') {
    return respond(mocks.siteSeries(siteId, range === '24h' ? 24 : 7 * 24), {
      mesures: [],
      predictions: [],
    })
  }
  return fromApi(
    async () => {
      const heures = range === '24h' ? 24 : 7 * 24
      const lignes = await fetchConsommation(siteId, debutAvant(heures))
      return {
        mesures: lignes.map(toConsumptionPoint),
        // Prévisions : US2. On ne mélange pas une prévision simulée avec des mesures réelles.
        predictions: [],
      }
    },
    { mesures: [], predictions: [] },
  )
}

export async function fetchSiteCosts(siteId: string) {
  if (SOURCES.mesures !== 'api') return respond(mocks.siteCosts(siteId))
  // 7 × 24 heures closes, pas depuis minuit d'il y a 6 jours : cette fenêtre fait moins de 7 jours.
  return fromApi(() => fetchConsommation(siteId, debutAvant(7 * 24)).then(costsFrom))
}

/** Transmission et capteurs de chaque site du périmètre (US4) */
export async function fetchSiteStatuses(): Promise<SiteStatus[]> {
  const reponse =
    SOURCES.etat === 'api'
      ? await fromApi(() => getJson<EtatSiteApi[]>('/sites/etat'), [])
      : await respond(mockEtats(), [])
  return reponse.map(toSiteStatus)
}

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
  if (SOURCES.recommandations !== 'api') {
    const reponse = await respond(
      structuredClone(mockRecommandations).filter((r) =>
        (STATUTS_EN_COURS as readonly string[]).includes(r.statut),
      ),
      [],
    )
    return reponse.map(toRecommendation)
  }
  return fromApi(async () => {
    const reponse = (
      await Promise.all(
        STATUTS_EN_COURS.map((statut) =>
          getJson<RecommandationApi[]>('/recommandations', { statut, limite: 500 }),
        ),
      )
    ).flat()
    return reponse.map(toRecommendation)
  }, [])
}

export const fetchPreviousSavings = (): Promise<number> => respond(mocks.economiesAnterieuresEur)

/**
 * Prend une alerte en compte : POST /api/alertes/{id}/prise-en-compte (US7). Déjà prise en
 * compte ou terminée, l'API répond 409 (ApiError). Simulée avec les alertes simulées : elle
 * échoue alors avec ?simulation=erreur, comme le ferait la vraie route.
 */
export async function acknowledgeAlert(alertId: string): Promise<string> {
  if (SOURCES.alertes !== 'api') return respond(alertId)
  await postJson<AlerteApi>(`/alertes/${alertId}/prise-en-compte`)
  return alertId
}

/**
 * Accepte ou refuse une recommandation : POST /api/recommandations/{id}/decision (US7).
 * Une décision est définitive : déjà décidée, l'API répond 409 (ApiError).
 */
export async function decideRecommendation(
  id: string,
  statut: 'acceptee' | 'refusee',
): Promise<{ id: string; statut: 'acceptee' | 'refusee' }> {
  if (SOURCES.recommandations !== 'api') return respond({ id, statut })
  const reponse = await postJson<RecommandationApi>(`/recommandations/${id}/decision`, { statut })
  return { id, statut: reponse.statut === 'refusee' ? 'refusee' : 'acceptee' }
}
