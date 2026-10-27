import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  apiFetch,
  checkAccount,
  CODE_COMPTE_NON_RATTACHE,
  ENTETE_ERREUR,
  onAccountChecked,
  onUnlinkedAccount,
} from '@/lib/api'
import { getToken, login } from '@/lib/auth'

vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })

// 403 d'un compte absent de app.utilisateur, tel que l'API le renvoie (api/auth.py)
const compteNonRattache = () =>
  json(
    403,
    { detail: 'Compte non rattaché à un client' },
    { [ENTETE_ERREUR]: CODE_COMPTE_NON_RATTACHE },
  )

// Chaque test retire ses écouteurs : ils ne doivent pas être appelés par les tests suivants
const retraits: (() => void)[] = []
const listen = () => {
  const listener = vi.fn<() => void>()
  retraits.push(onUnlinkedAccount(listener))
  return listener
}
afterEach(() => retraits.splice(0).forEach((retirer) => retirer()))

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
    const listener = listen()
    fetchMock.mockResolvedValue(compteNonRattache())

    const response = await apiFetch('/sites', {}, '/api')

    expect(listener).toHaveBeenCalledOnce()
    // Le corps n'a pas été consommé : l'appelant peut encore le lire
    expect(await response.json()).toEqual({ detail: 'Compte non rattaché à un client' })
  })

  it('reconnaît le compte au code de l’en-tête, pas au message', async () => {
    const listener = listen()
    // Même message, sans le code : un autre 403, pas un compte non rattaché
    fetchMock.mockResolvedValue(json(403, { detail: 'Compte non rattaché à un client' }))

    await apiFetch('/sites', {}, '/api')

    expect(listener).not.toHaveBeenCalled()
  })

  it('ne confond pas un rôle insuffisant avec un compte non rattaché', async () => {
    const listener = listen()
    fetchMock.mockResolvedValue(json(403, { detail: 'Rôle insuffisant' }))

    await apiFetch('/sites', {}, '/api')

    expect(listener).not.toHaveBeenCalled()
  })

  it('un écouteur retiré n’est plus appelé', async () => {
    const listener = vi.fn<() => void>()
    onUnlinkedAccount(listener)()
    fetchMock.mockResolvedValue(compteNonRattache())

    await apiFetch('/sites', {}, '/api')

    expect(listener).not.toHaveBeenCalled()
  })
})

describe('checkAccount (GET /api/moi après la connexion)', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => vi.stubGlobal('fetch', fetchMock))
  afterEach(() => vi.unstubAllGlobals())

  it('appelle /api/moi avec le jeton : compte reconnu, sites transmis', async () => {
    const moi = { id: 'x', id_client: 1, roles: ['GESTION-SITE'], sites: ['SITE002'] }
    fetchMock.mockResolvedValue(json(200, moi))
    const listener = vi.fn<(moi: unknown) => void>()
    const retirer = onAccountChecked(listener)

    expect(await checkAccount('/api')).toBe('ok')
    retirer()

    expect(listener).toHaveBeenCalledWith(moi)

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/moi')
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer jeton-de-test')
  })

  it('détecte un compte non rattaché', async () => {
    fetchMock.mockResolvedValue(compteNonRattache())
    expect(await checkAccount('/api')).toBe('unlinked')
  })

  it('abandonne /api/moi au-delà du délai : l’application démarre quand même', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    // API bloquée : la réponse n'arrive jamais, seul l'abandon termine l'appel
    fetchMock.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) =>
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('Délai dépassé', 'AbortError')),
          ),
        ),
    )

    expect(await checkAccount('/api', 20)).toBe('unavailable')
  })

  it('laisse démarrer l’application si l’API est injoignable ou en erreur', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    expect(await checkAccount('/api')).toBe('unavailable')

    fetchMock.mockResolvedValueOnce(json(503, { detail: 'Keycloak injoignable' }))
    expect(await checkAccount('/api')).toBe('unavailable')
  })
})
