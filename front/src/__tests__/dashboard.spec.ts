import { describe, expect, it } from 'vitest'

import {
  fetchAlerts,
  fetchKpis,
  fetchOverview,
  fetchSiteCosts,
  fetchSiteOverview,
  fetchSiteSeries,
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
