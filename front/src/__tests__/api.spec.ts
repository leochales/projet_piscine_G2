import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  apiFetch,
  checkAccount,
  DETAIL_COMPTE_NON_RATTACHE,
  onUnlinkedAccount,
} from '@/lib/api'
import { getToken, login } from '@/lib/auth'

vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

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

  it('prévient l’application d’un compte non rattaché, et rend la réponse lisible', async () => {
    const listener = vi.fn<() => void>()
    onUnlinkedAccount(listener)
    fetchMock.mockResolvedValue(json(403, { detail: DETAIL_COMPTE_NON_RATTACHE }))

    const response = await apiFetch('/sites', {}, '/api')

    expect(listener).toHaveBeenCalledOnce()
    // Le corps n'a pas été consommé : l'appelant peut encore le lire
    expect(await response.json()).toEqual({ detail: DETAIL_COMPTE_NON_RATTACHE })
  })

  it('ne confond pas un rôle insuffisant avec un compte non rattaché', async () => {
    const listener = vi.fn<() => void>()
    onUnlinkedAccount(listener)
    fetchMock.mockResolvedValue(json(403, { detail: 'Rôle insuffisant' }))

    await apiFetch('/sites', {}, '/api')

    expect(listener).not.toHaveBeenCalled()
  })
})

describe('checkAccount (GET /api/moi après la connexion)', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => vi.stubGlobal('fetch', fetchMock))
  afterEach(() => vi.unstubAllGlobals())

  it('appelle /api/moi avec le jeton : compte reconnu', async () => {
    fetchMock.mockResolvedValue(json(200, { id: 'x', id_client: 1, roles: ['CONSULT-SITE'] }))

    expect(await checkAccount('/api')).toBe('ok')

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/moi')
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer jeton-de-test')
  })

  it('détecte un compte non rattaché', async () => {
    fetchMock.mockResolvedValue(json(403, { detail: DETAIL_COMPTE_NON_RATTACHE }))
    expect(await checkAccount('/api')).toBe('unlinked')
  })

  it('laisse démarrer l’application si l’API est injoignable ou en erreur', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    expect(await checkAccount('/api')).toBe('unavailable')

    fetchMock.mockResolvedValueOnce(json(503, { detail: 'Keycloak injoignable' }))
    expect(await checkAccount('/api')).toBe('unavailable')
  })
})
