import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch } from '@/lib/api'
import { getToken, login } from '@/lib/auth'

vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

describe('apiFetch', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    vi.mocked(login).mockClear()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('ajoute le jeton de l’utilisateur à l’appel /api', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }))
    await apiFetch('/sites', { headers: { Accept: 'application/json' } }, '/api')

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/sites')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer jeton-de-test')
    expect(headers.get('Accept')).toBe('application/json')
    expect(getToken).toHaveBeenCalled()
  })

  it('relance la connexion quand l’API répond 401', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 401 }))
    await expect(apiFetch('/sites', {}, '/api')).rejects.toBeInstanceOf(ApiError)
    expect(login).toHaveBeenCalledOnce()
  })

  it('renvoie les autres réponses sans relancer la connexion', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 403 }))
    const response = await apiFetch('/sites', {}, '/api')
    expect(response.status).toBe(403)
    expect(login).not.toHaveBeenCalled()
  })
})
