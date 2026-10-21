// Point d'accès unique aux données du dashboard.
// Les vues n'importent que ce fichier : brancher l'API ne changera que lui.

import * as mocks from '@/mocks/data'
import type { Alert, FleetKpis, Recommendation, SiteOverview, SiteSeries } from '@/types/energy'

export type SeriesRange = '24h' | '7j'

const delay = <T>(value: T) => new Promise<T>((resolve) => setTimeout(() => resolve(value), 150))

export const fetchKpis = (): Promise<FleetKpis> => delay(mocks.kpis)

export const fetchOverview = (): Promise<SiteOverview[]> => delay(mocks.overview)

export const fetchSiteOverview = (siteId: string): Promise<SiteOverview | undefined> =>
  delay(mocks.overview.find((o) => o.site.id === siteId))

export const fetchSiteSeries = (siteId: string, range: SeriesRange): Promise<SiteSeries> =>
  delay(mocks.siteSeries(siteId, range === '24h' ? 24 : 7 * 24))

export const fetchSiteCosts = (siteId: string) => delay(mocks.siteCosts(siteId))

export const fetchAlerts = (): Promise<Alert[]> => delay(structuredClone(mocks.alerts))

export const fetchRecommendations = (): Promise<Recommendation[]> =>
  delay(structuredClone(mocks.recommendations))

export const fetchPreviousSavings = (): Promise<number> => delay(mocks.economiesAnterieuresEur)
