import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref, shallowRef } from 'vue'

import { REFRESH_INTERVAL_MS, useAutoRefresh } from '@/lib/refresh'
import type { RequestStatus } from '@/lib/request'

/** Requête simulée : compte ses rechargements, et réussit ou échoue à la demande */
function fakeRequest(updatedAt?: Date) {
  const request = {
    status: ref<RequestStatus>(updatedAt ? 'success' : 'loading'),
    updatedAt: shallowRef(updatedAt),
    fail: false,
    reload: vi.fn<() => Promise<void>>(async () => {
      request.status.value = request.fail ? 'error' : 'success'
      if (!request.fail) request.updatedAt.value = new Date()
    }),
  }
  return request
}

/** Onglet affiché ou masqué : jsdom ne le simule pas, on déclenche l'événement à la main */
async function setTabVisible(visible: boolean) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => (visible ? 'visible' : 'hidden'),
  })
  document.dispatchEvent(new Event('visibilitychange'))
  await nextTick()
}

beforeEach(async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-23T12:00:00Z'))
  await setTabVisible(true)
})

afterEach(() => vi.useRealTimers())

describe('useAutoRefresh', () => {
  it('rafraîchit toutes les requêtes à chaque intervalle', async () => {
    const a = fakeRequest(new Date())
    const b = fakeRequest(new Date())
    useAutoRefresh([a, b])

    await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS - 1)
    expect(a.reload).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(a.reload).toHaveBeenCalledOnce()
    expect(b.reload).toHaveBeenCalledOnce()
  })

  it('se met en pause quand l’onglet est masqué', async () => {
    const a = fakeRequest(new Date())
    useAutoRefresh([a])

    await setTabVisible(false)
    await vi.advanceTimersByTimeAsync(5 * REFRESH_INTERVAL_MS)
    expect(a.reload).not.toHaveBeenCalled()
  })

  it('au retour sur l’onglet, rafraîchit tout de suite si les données sont trop anciennes', async () => {
    const a = fakeRequest(new Date())
    useAutoRefresh([a])
    await setTabVisible(false)

    vi.setSystemTime(Date.now() + REFRESH_INTERVAL_MS)
    await setTabVisible(true)
    expect(a.reload).toHaveBeenCalledOnce()
  })

  it('au retour sur l’onglet, ne rafraîchit pas des données encore fraîches', async () => {
    const a = fakeRequest(new Date())
    useAutoRefresh([a])
    await setTabVisible(false)

    vi.setSystemTime(Date.now() + 10_000)
    await setTabVisible(true)
    expect(a.reload).not.toHaveBeenCalled()
  })

  it('donne la fraîcheur de la plus ancienne donnée affichée', () => {
    const old = new Date('2026-10-23T11:58:00Z')
    const recent = new Date('2026-10-23T11:59:30Z')
    const { updatedAt } = useAutoRefresh([fakeRequest(recent), fakeRequest(old)])
    expect(updatedAt.value).toEqual(old)
  })

  it('n’a pas de fraîcheur tant qu’une requête n’a jamais répondu', () => {
    const { updatedAt } = useAutoRefresh([fakeRequest(new Date()), fakeRequest()])
    expect(updatedAt.value).toBeUndefined()
  })

  it('signale un rafraîchissement en cours, puis un échec', async () => {
    const a = fakeRequest(new Date())
    const { refresh, refreshing, failed } = useAutoRefresh([a])

    a.status.value = 'loading'
    expect(refreshing.value).toBe(true)

    a.fail = true
    await refresh()
    expect(refreshing.value).toBe(false)
    expect(failed.value).toBe(true)
  })
})
