import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  acknowledgeAlert,
  decideRecommendation,
  fetchAlerts,
  fetchKpis,
  fetchOverview,
  fetchSiteCosts,
  fetchSiteOverview,
  fetchRecommendations,
  fetchSiteSeries,
  readSimulation,
  SLOW_DELAY_MS,
} from '@/services/dashboard'

describe('services/dashboard', () => {
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
  const simulate = (value: string) => window.history.replaceState(null, '', `/?simulation=${value}`)

  afterEach(() => {
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
