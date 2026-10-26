import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import * as service from '@/services/dashboard'
import { monthlyGain, useOperationsStore } from '@/stores/operations'
import { useUserStore } from '@/stores/user'
import type { Recommendation } from '@/types/energy'

const rec = (over: Partial<Recommendation>): Recommendation => ({
  id: 'R',
  siteId: 'SITE002',
  nomSite: 'Usine de Lyon',
  titre: 'Test',
  description: null,
  alerteId: null,
  gainEstimeEur: 100,
  periodeGain: 'unique',
  statut: 'proposee',
  creeeLe: '2026-10-26T08:00:00Z',
  ...over,
})

describe('useOperationsStore', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('ramène un gain hebdomadaire au mois', () => {
    expect(monthlyGain(rec({ periodeGain: 'unique' }))).toBe(100)
    expect(monthlyGain(rec({ periodeGain: 'semaine' }))).toBeCloseTo((100 * 52) / 12)
  })

  it('compte 0 € pour un gain pas encore estimé', () => {
    expect(monthlyGain(rec({ gainEstimeEur: null, periodeGain: null }))).toBe(0)
  })

  it('ne compte que les recommandations acceptées dans les économies', () => {
    const store = useOperationsStore()
    store.recommendations = [
      rec({ id: 'A', gainEstimeEur: 380, statut: 'acceptee' }),
      rec({ id: 'B', gainEstimeEur: 45, periodeGain: 'semaine', statut: 'refusee' }),
    ]
    expect(store.savings).toBe(380)
  })

  it('enregistre la décision sur une recommandation', async () => {
    const store = useOperationsStore()
    store.recommendations = [rec({ id: 'A' }), rec({ id: 'B' })]
    await store.decide('A', 'acceptee')
    await store.decide('B', 'refusee')
    await store.decide('inconnue', 'acceptee') // sans effet
    expect(store.recommendations.map((r) => r.statut)).toEqual(['acceptee', 'refusee'])
  })

  it('compte les alertes critiques restant à traiter', async () => {
    const store = useOperationsStore()
    await store.load()
    const critical = store.alerts.find((a) => a.gravite === 'critique')!
    expect(store.pendingCritical).toBe(1)
    await store.acknowledge(critical.id)
    await store.acknowledge('inconnue') // sans effet
    expect(store.pendingCritical).toBe(0)
  })

  it('ne lance qu’un chargement quand l’en-tête et l’écran le demandent en même temps', async () => {
    const spy = vi.spyOn(service, 'fetchRecommendations')
    const store = useOperationsStore()

    await Promise.all([store.load(), store.load()])

    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it('un rechargement des recommandations garde les décisions prises', async () => {
    const store = useOperationsStore()
    await store.load()
    const id = store.recommendations[0]!.id
    await store.decide(id, 'refusee')

    await store.reloadRecommendations()

    expect(store.recommendations.find((r) => r.id === id)?.statut).toBe('refusee')
  })

  it('une décision confirmée pendant un rechargement s’applique à la liste rechargée', async () => {
    const store = useOperationsStore()
    await store.load()
    const id = store.recommendations[0]!.id

    const decision = store.decide(id, 'acceptee')
    await store.reloadRecommendations() // la liste est remplacée pendant l'envoi
    await decision

    expect(store.recommendations.find((r) => r.id === id)?.statut).toBe('acceptee')
  })

  it('ne recharge pas les données déjà chargées', async () => {
    const store = useOperationsStore()
    await store.load()
    await store.acknowledge(store.alerts[0]!.id)
    await store.load()
    expect(store.alerts[0]!.priseEnCompte).toBe(true)
  })

  it("retire une alerte prise en compte du compteur d'alertes actives", async () => {
    const store = useOperationsStore()
    await store.load()
    const before = store.pendingAlerts.length
    await store.acknowledge(store.alerts[0]!.id)
    expect(store.pendingAlerts).toHaveLength(before - 1)
  })

  describe('envoi des actions', () => {
    afterEach(() => vi.restoreAllMocks())

    it('n’affiche rien comme fait si le service échoue, et remonte l’erreur', async () => {
      const store = useOperationsStore()
      await store.load()
      const alert = store.alerts[0]!
      store.recommendations = [rec({ id: 'A' })]
      vi.spyOn(service, 'acknowledgeAlert').mockRejectedValue(new Error('panne'))
      vi.spyOn(service, 'decideRecommendation').mockRejectedValue(new Error('panne'))

      await expect(store.acknowledge(alert.id)).rejects.toThrow('panne')
      await expect(store.decide('A', 'acceptee')).rejects.toThrow('panne')
      expect(alert.priseEnCompte).toBe(false)
      expect(store.recommendations[0]!.statut).toBe('proposee')
      expect(store.pending.size).toBe(0)
    })

    it('bloque l’élément pendant l’envoi, et n’envoie pas deux fois la même action', async () => {
      const store = useOperationsStore()
      await store.load()
      const alert = store.alerts[0]!
      const send = vi.spyOn(service, 'acknowledgeAlert')

      const first = store.acknowledge(alert.id)
      expect(store.pending.has(alert.id)).toBe(true)
      await store.acknowledge(alert.id) // double clic
      await first

      expect(send).toHaveBeenCalledOnce()
      expect(store.pending.has(alert.id)).toBe(false)
      expect(alert.priseEnCompte).toBe(true)
    })

    it('retient qui a pris l’alerte en compte, et quand', async () => {
      const store = useOperationsStore()
      await store.load()
      const alert = store.alerts.find((a) => !a.priseEnCompte)!
      const before = Date.now()

      await store.acknowledge(alert.id)
      expect(alert.prisePar).toBe(useUserStore().nom)
      expect(new Date(alert.priseLe!).getTime()).toBeGreaterThanOrEqual(before)
    })

    it('ne renvoie pas la prise en compte d’une alerte déjà prise en compte (US7)', async () => {
      const store = useOperationsStore()
      await store.load()
      const alert = store.alerts[0]!
      await store.acknowledge(alert.id)
      const send = vi.spyOn(service, 'acknowledgeAlert')

      await store.acknowledge(alert.id)
      expect(send).not.toHaveBeenCalled()
    })
  })
})
