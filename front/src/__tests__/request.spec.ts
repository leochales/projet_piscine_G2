import { describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'

import { useRequest } from '@/lib/request'

/** Promesse résolue ou rejetée à la main, pour contrôler l'ordre des réponses */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useRequest', () => {
  it('passe de « chargement » à « succès » avec les données', async () => {
    const request = useRequest(async () => 42)
    expect(request.status.value).toBe('loading')
    expect(request.data.value).toBeUndefined()

    await flushPromises()
    expect(request.status.value).toBe('success')
    expect(request.data.value).toBe(42)
  })

  it('signale une erreur, puis réussit au « Réessayer »', async () => {
    let fail = true
    const request = useRequest(async () => {
      if (fail) throw new Error('API injoignable')
      return 'ok'
    })
    await flushPromises()
    expect(request.status.value).toBe('error')
    expect(request.error.value).toBeInstanceOf(Error)

    fail = false
    const retry = request.reload()
    expect(request.status.value).toBe('loading')
    expect(request.error.value).toBeUndefined()
    await retry
    expect(request.status.value).toBe('success')
    expect(request.data.value).toBe('ok')
  })

  it('garde les données affichées pendant un rechargement et après un échec', async () => {
    let fail = false
    const request = useRequest(async () => {
      if (fail) throw new Error('coupure')
      return [1, 2, 3]
    })
    await flushPromises()

    fail = true
    const refresh = request.reload()
    expect(request.data.value).toEqual([1, 2, 3])
    await refresh
    expect(request.status.value).toBe('error')
    expect(request.data.value).toEqual([1, 2, 3])
  })

  it('ignore la réponse d’un appel dépassé par un plus récent', async () => {
    const slow = deferred<string>()
    const fast = deferred<string>()
    const calls = [slow, fast]
    const request = useRequest(() => calls.shift()!.promise)

    const second = request.reload()
    fast.resolve('récent')
    await second
    slow.resolve('ancien')
    await flushPromises()

    expect(request.data.value).toBe('récent')
    expect(request.status.value).toBe('success')
  })

  it('ignore aussi l’erreur d’un appel dépassé', async () => {
    const old = deferred<string>()
    const calls = [old.promise, Promise.resolve('récent')]
    const request = useRequest(() => calls.shift()!)

    await request.reload()
    old.reject(new Error('trop tard'))
    await flushPromises()

    expect(request.status.value).toBe('success')
    expect(request.data.value).toBe('récent')
  })

  it('recharge quand la valeur surveillée change, sans montrer les anciennes données', async () => {
    const siteId = ref('SITE001')
    const pending: ReturnType<typeof deferred<string>>[] = []
    const request = useRequest(
      () => {
        const call = deferred<string>()
        pending.push(call)
        return call.promise
      },
      { watch: siteId },
    )
    pending[0]!.resolve('courbe de SITE001')
    await flushPromises()
    expect(request.data.value).toBe('courbe de SITE001')

    siteId.value = 'SITE002'
    await nextTick()
    expect(pending).toHaveLength(2)
    expect(request.data.value).toBeUndefined()
    expect(request.status.value).toBe('loading')

    pending[1]!.resolve('courbe de SITE002')
    await flushPromises()
    expect(request.data.value).toBe('courbe de SITE002')
  })
})
