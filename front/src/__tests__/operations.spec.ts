import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { monthlyGain, useOperationsStore } from '@/stores/operations'
import type { Recommendation } from '@/types/energy'

const rec = (over: Partial<Recommendation>): Recommendation => ({
  id: 'R',
  siteId: 'SITE002',
  titre: 'Test',
  alerteLiee: null,
  gainEstimeEur: 100,
  periodeGain: 'ponctuel',
  statut: 'proposee',
  ...over,
})

describe('useOperationsStore', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('ramène un gain hebdomadaire au mois', () => {
    expect(monthlyGain(rec({ periodeGain: 'ponctuel' }))).toBe(100)
    expect(monthlyGain(rec({ periodeGain: 'semaine' }))).toBeCloseTo((100 * 52) / 12)
  })

  it('ne compte que les recommandations acceptées dans les économies', () => {
    const store = useOperationsStore()
    store.recommendations = [
      rec({ id: 'A', gainEstimeEur: 380, statut: 'acceptee' }),
      rec({ id: 'B', gainEstimeEur: 45, periodeGain: 'semaine', statut: 'refusee' }),
    ]
    expect(store.savings).toBe(380)
  })

  it('enregistre la décision sur une recommandation', () => {
    const store = useOperationsStore()
    store.recommendations = [rec({ id: 'A' }), rec({ id: 'B' })]
    store.decide('A', 'acceptee')
    store.decide('B', 'refusee')
    store.decide('inconnue', 'acceptee') // sans effet
    expect(store.recommendations.map((r) => r.statut)).toEqual(['acceptee', 'refusee'])
  })

  it('compte les alertes critiques restant à traiter', async () => {
    const store = useOperationsStore()
    await store.load()
    const critical = store.alerts.find((a) => a.gravite === 'critique')!
    expect(store.pendingCritical).toBe(1)
    store.acknowledge(critical.id)
    store.acknowledge('inconnue') // sans effet
    expect(store.pendingCritical).toBe(0)
  })

  it('ne recharge pas les données déjà chargées', async () => {
    const store = useOperationsStore()
    await store.load()
    store.acknowledge(store.alerts[0]!.id)
    await store.load()
    expect(store.alerts[0]!.priseEnCompte).toBe(true)
  })

  it("retire une alerte prise en compte du compteur d'alertes actives", async () => {
    const store = useOperationsStore()
    await store.load()
    const before = store.pendingAlerts.length
    store.acknowledge(store.alerts[0]!.id)
    expect(store.pendingAlerts).toHaveLength(before - 1)
  })
})
