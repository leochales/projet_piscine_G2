import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/services/http'
import {
  acknowledgeAlert,
  decideRecommendation,
  fetchAlerts,
  fetchFleetTrend,
  fetchKpis,
  fetchOverview,
  fetchSiteCosts,
  fetchSiteOverview,
  fetchRecommendations,
  fetchSiteSeries,
  readSimulation,
  SLOW_DELAY_MS,
  SOURCES,
} from '@/services/dashboard'

vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

describe('services/dashboard', () => {
  beforeEach(() => {
    SOURCES.mesures = 'mock'
  })

  afterEach(() => {
    SOURCES.mesures = 'api'
  })

  it('charge 24 h ou 7 jours d’historique selon la période', async () => {
    const day = await fetchSiteSeries('SITE002', '24h')
    const week = await fetchSiteSeries('SITE002', '7j')
    // +1 : le point « maintenant » est inclus
    expect(day.mesures).toHaveLength(24 + 1)
    expect(week.mesures).toHaveLength(7 * 24 + 1)
    // La prédiction couvre toujours 48 h, quelle que soit la période affichée
    expect(day.predictions).toHaveLength(48 + 1)
  })

  it('trouve un site, ou rien si l’identifiant est inconnu', async () => {
    expect((await fetchSiteOverview('SITE002'))?.site.nom).toBe('Usine de Lyon')
    expect(await fetchSiteOverview('SITE999')).toBeUndefined()
  })

  it('donne les indicateurs, les sites et des coûts positifs', async () => {
    expect((await fetchKpis()).nbSites).toBe(7)
    expect(await fetchOverview()).toHaveLength(7)
  })

  it('donne l’évolution du parc : 24 h de consommation, 7 jours de coût', async () => {
    const { consommationKw24h, coutEurJours7 } = await fetchFleetTrend()
    expect(consommationKw24h).toHaveLength(24 + 1) // le point « maintenant » est inclus
    expect(coutEurJours7).toHaveLength(7)
    expect([...consommationKw24h, ...coutEurJours7].every((v) => v > 0)).toBe(true)
  })

  it('finit les mini-courbes sur les valeurs des KPI, et respecte la variation « vs hier »', async () => {
    const [kpis, { consommationKw24h, coutEurJours7 }] = await Promise.all([
      fetchKpis(),
      fetchFleetTrend(),
    ])
    expect(consommationKw24h[consommationKw24h.length - 1]).toBe(kpis.consommationKw)
    const [yesterday, today] = coutEurJours7.slice(-2) as [number, number]
    expect(today).toBe(kpis.coutJourEur)
    expect(((today - yesterday) / yesterday) * 100).toBeCloseTo(kpis.variationCoutPct, 0)
  })

  it('exclut du total du parc les sites sans mesure, et le signale', async () => {
    const [kpis, sites] = await Promise.all([fetchKpis(), fetchOverview()])
    const measured = sites.filter((s) => s.consommationKw !== null)
    expect(kpis.nbSitesSansMesure).toBe(sites.length - measured.length)
    expect(kpis.consommationKw).toBe(measured.reduce((t, s) => t + s.consommationKw!, 0))
    const costs = await fetchSiteCosts('SITE001')
    expect(costs.coutEur).toBeGreaterThan(0)
    expect(costs.co2Tonnes).toBeGreaterThan(0)
  })

  it('renvoie une copie des alertes : une action ne modifie pas les données sources', async () => {
    const first = await fetchAlerts()
    first[0]!.priseEnCompte = true
    expect((await fetchAlerts())[0]!.priseEnCompte).toBe(false)
  })
})

describe('simulation des cas réels (?simulation=…)', () => {
  beforeEach(() => {
    SOURCES.mesures = 'mock'
  })

  const simulate = (value: string) => window.history.replaceState(null, '', `/?simulation=${value}`)

  afterEach(() => {
    SOURCES.mesures = 'api'
    window.history.replaceState(null, '', '/')
    vi.useRealTimers()
  })

  it('lit la simulation demandée, et seulement en développement', () => {
    expect(readSimulation('?simulation=erreur', true)).toBe('erreur')
    expect(readSimulation('?simulation=inconnue', true)).toBeNull()
    expect(readSimulation('', true)).toBeNull()
    expect(readSimulation('?simulation=erreur', false)).toBeNull()
  })

  it('« erreur » fait échouer les appels, actions comprises', async () => {
    simulate('erreur')
    await expect(fetchOverview()).rejects.toThrow('API simulée en erreur')
    await expect(acknowledgeAlert('A1')).rejects.toThrow('API simulée en erreur')
    await expect(decideRecommendation('R1', 'acceptee')).rejects.toThrow('API simulée en erreur')
  })

  it('confirme les actions simulées', async () => {
    expect(await acknowledgeAlert('A1')).toBe('A1')
    expect(await decideRecommendation('R1', 'refusee')).toEqual({ id: 'R1', statut: 'refusee' })
  })

  it('« vide » renvoie des listes et des courbes vides', async () => {
    simulate('vide')
    expect(await fetchOverview()).toEqual([])
    expect(await fetchAlerts()).toEqual([])
    expect(await fetchRecommendations()).toEqual([])
    expect(await fetchSiteSeries('SITE002', '24h')).toEqual({ mesures: [], predictions: [] })
    expect(await fetchFleetTrend()).toEqual({ consommationKw24h: [], coutEurJours7: [] })
    // Les indicateurs du parc n'ont pas de version « vide » : ils restent renseignés
    expect((await fetchKpis()).nbSites).toBe(7)
  })

  it('« lent » retarde la réponse', async () => {
    vi.useFakeTimers()
    simulate('lent')
    let done = false
    const call = fetchOverview().then(() => (done = true))

    await vi.advanceTimersByTimeAsync(SLOW_DELAY_MS - 1)
    expect(done).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    await call
    expect(done).toBe(true)
  })
})

describe('mesures : source API', () => {
  const derniere = {
    id_site: 'SITE001',
    nom: 'Bureau Paris La Défense',
    type: 'office',
    capacite_kw: 200,
    horodatage: '2026-10-27T09:05:00Z',
    consommation_kw: 120,
    data_quality: 'good',
  }

  function stubFetch(reponse: (url: string) => { status: number; body: unknown }) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const { status, body } = reponse(String(url))
        return new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
  }

  beforeEach(() => {
    SOURCES.mesures = 'api'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lit la dernière mesure de chaque site', async () => {
    stubFetch((url) => {
      expect(url).toBe('/api/sites/derniere-mesure')
      return { status: 200, body: [derniere] }
    })

    const sites = await fetchOverview()

    expect(sites).toHaveLength(1)
    expect(sites[0]).toMatchObject({
      site: { id: 'SITE001', nom: 'Bureau Paris La Défense', type: 'bureaux' },
      consommationKw: 120,
      mesureLe: '2026-10-27T09:05:00Z',
    })
  })

  it('remonte l’erreur de la route', async () => {
    stubFetch(() => ({ status: 503, body: { detail: 'indisponible' } }))

    await expect(fetchOverview()).rejects.toBeInstanceOf(ApiError)
  })

  it('garde une heure sans kWh dans la courbe', async () => {
    stubFetch((url) => {
      if (!url.includes('/consommation')) return { status: 200, body: [] }
      return {
        status: 200,
        body: [
          { heure: '2026-10-27T08:00:00Z', consommation_kwh: 10, cout_eur: 1.4 },
          { heure: '2026-10-27T09:00:00Z', consommation_kwh: null, cout_eur: null },
        ],
      }
    })

    const series = await fetchSiteSeries('SITE001', '24h')

    expect(series.mesures.map((point) => point.kw)).toEqual([10, null])
  })

  it('ne demande la dernière mesure et la consommation du parc qu’une fois', async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      if (url.includes('derniere-mesure')) return { status: 200, body: [derniere] }
      return { status: 200, body: [] }
    })

    await Promise.all([fetchKpis(), fetchOverview(), fetchFleetTrend()])

    expect(urls.filter((url) => url.includes('derniere-mesure'))).toHaveLength(1)
    expect(urls.filter((url) => url.includes('/consommation'))).toHaveLength(1)
  })
})
