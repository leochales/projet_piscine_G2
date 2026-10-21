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

  it("retire une alerte prise en compte du compteur d'alertes actives", async () => {
    const store = useOperationsStore()
    await store.load()
    const before = store.pendingAlerts.length
    store.acknowledge(store.alerts[0]!.id)
    expect(store.pendingAlerts).toHaveLength(before - 1)
  })
})
