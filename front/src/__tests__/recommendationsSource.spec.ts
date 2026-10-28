import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { decideRecommendation, fetchRecommendations, SOURCES } from '@/services/dashboard'
import { login } from '@/lib/auth'
import { ApiError, getJson } from '@/services/http'
import { recommandations } from '@/mocks/recommandations'

// Jeton simulé : getJson passe par apiFetch, qui demande le jeton à Keycloak
vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

function stubFetch(status: number, body: unknown) {
  // Une réponse neuve à chaque appel : le corps d'une Response ne se lit qu'une fois
  const fetchMock = vi.fn<typeof fetch>(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  SOURCES.recommandations = 'mock'
})

afterEach(() => {
  SOURCES.recommandations = 'api'
  vi.unstubAllGlobals()
})

describe('fetchRecommendations : données simulées ou API', () => {
  it('avec la source « mock », renvoie les recommandations simulées en cours, converties', async () => {
    const fetchMock = stubFetch(200, [])

    const liste = await fetchRecommendations()

    expect(fetchMock).not.toHaveBeenCalled()
    // Les refusées ne sont pas chargées
    const enCours = recommandations.filter((r) => r.statut !== 'refusee')
    expect(liste.map((r) => r.id)).toEqual(enCours.map((r) => String(r.id_recommandation)))
    expect(liste[0]).toMatchObject({ id: '1', siteId: 'SITE002', nomSite: 'Usine de Lyon' })
  })

  it('avec la source « api », lit une page par statut en cours, au même format', async () => {
    SOURCES.recommandations = 'api'
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 28, 11, 30))
    const fetchMock = stubFetch(200, [recommandations[3]])

    const liste = await fetchRecommendations()

    // Une requête par statut : la limite de 500 n'écarte pas les propositions anciennes.
    // À décider : alerte en cours ; acceptées : depuis le 1er du mois, heure locale.
    const debutDuMois = encodeURIComponent(new Date(2026, 9, 1).toISOString())
    const urls = fetchMock.mock.calls.map(([url]) => url)
    expect(urls).toEqual([
      '/api/recommandations?statut=proposee&alerte_en_cours=true&limite=500',
      `/api/recommandations?statut=acceptee&decidee_depuis=${debutDuMois}&limite=500`,
    ])
    expect(liste).toHaveLength(2)
    expect(liste[0]).toMatchObject({ id: '4', siteId: 'SITE006' })
    vi.useRealTimers()
  })

  it('avec la source « api », remonte l’erreur de la route', async () => {
    SOURCES.recommandations = 'api'
    stubFetch(503, { detail: 'indisponible' })

    await expect(fetchRecommendations()).rejects.toBeInstanceOf(ApiError)
  })
})

describe('getJson', () => {
  it('envoie le jeton Keycloak (apiFetch) : l’API le vérifie à chaque requête', async () => {
    const fetchMock = stubFetch(200, [])

    await getJson('/recommandations', { statut: 'proposee' })

    const [, init] = fetchMock.mock.calls[0]!
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer jeton-de-test')
    expect(new Headers(init?.headers).get('Accept')).toBe('application/json')
  })

  it('n’envoie pas les paramètres vides', async () => {
    const fetchMock = stubFetch(200, [])

    await getJson('/alertes', { id_site: 'SITE002', statut: null, en_cours: undefined })

    expect(fetchMock).toHaveBeenCalledWith('/api/alertes?id_site=SITE002', expect.anything())
  })

  it('lève ApiError avec le code HTTP', async () => {
    stubFetch(503, { detail: 'Indisponible' })

    await expect(getJson('/recommandations')).rejects.toMatchObject({ status: 503 })
  })

  it('session expirée (401) : relance la connexion Keycloak', async () => {
    stubFetch(401, { detail: 'Jeton invalide' })

    await expect(getJson('/recommandations')).rejects.toBeInstanceOf(ApiError)
    expect(login).toHaveBeenCalled()
  })
})

describe('décisions', () => {
  it('sont simulées avec les données simulées', async () => {
    const fetchMock = stubFetch(200, {})
    expect(await decideRecommendation('1', 'acceptee')).toEqual({ id: '1', statut: 'acceptee' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('avec les vraies données, sont enregistrées par POST /api/recommandations/{id}/decision (US7)', async () => {
    SOURCES.recommandations = 'api'
    const fetchMock = stubFetch(200, { ...recommandations[0], statut: 'refusee' })

    expect(await decideRecommendation('1', 'refusee')).toEqual({ id: '1', statut: 'refusee' })

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/recommandations/1/decision')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ statut: 'refusee' })
  })

  it('une recommandation déjà décidée lève une erreur 409', async () => {
    SOURCES.recommandations = 'api'
    stubFetch(409, { detail: 'Recommandation déjà décidée' })

    await expect(decideRecommendation('1', 'acceptee')).rejects.toMatchObject({ status: 409 })
  })
})
