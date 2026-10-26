import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  canDecideRecommendations,
  decideRecommendation,
  fetchRecommendations,
  SOURCES,
} from '@/services/dashboard'
import { ApiError, getJson } from '@/services/http'
import { recommandations } from '@/mocks/recommandations'

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

afterEach(() => {
  SOURCES.recommandations = 'mock'
  vi.unstubAllGlobals()
})

describe('fetchRecommendations : données simulées ou API', () => {
  it('par défaut, renvoie les recommandations simulées en cours, converties', async () => {
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
    const fetchMock = stubFetch(200, [recommandations[3]])

    const liste = await fetchRecommendations()

    // Une requête par statut : la limite de 500 n'écarte pas les propositions anciennes
    const urls = fetchMock.mock.calls.map(([url]) => url)
    expect(urls).toEqual([
      '/api/recommandations?statut=proposee&limite=500',
      '/api/recommandations?statut=acceptee&limite=500',
    ])
    expect(liste).toHaveLength(2)
    expect(liste[0]).toMatchObject({ id: '4', siteId: 'SITE006' })
  })

  it('avec la source « api », remonte l’erreur de la route', async () => {
    SOURCES.recommandations = 'api'
    stubFetch(503, { detail: 'indisponible' })

    await expect(fetchRecommendations()).rejects.toBeInstanceOf(ApiError)
  })
})

describe('getJson', () => {
  it('n’envoie pas les paramètres vides', async () => {
    const fetchMock = stubFetch(200, [])

    await getJson('/alertes', { id_site: 'SITE002', statut: null, en_cours: undefined })

    expect(fetchMock).toHaveBeenCalledWith('/api/alertes?id_site=SITE002', expect.anything())
  })

  it('lève ApiError avec le code HTTP', async () => {
    stubFetch(401, { detail: 'Jeton manquant' })

    await expect(getJson('/recommandations')).rejects.toMatchObject({ status: 401 })
  })
})

describe('décisions', () => {
  it('sont possibles avec les données simulées', async () => {
    expect(canDecideRecommendations()).toBe(true)
    expect(await decideRecommendation('1', 'acceptee')).toEqual({ id: '1', statut: 'acceptee' })
  })

  it('sont refusées avec les vraies données, faute de route pour les enregistrer (US7)', async () => {
    SOURCES.recommandations = 'api'
    expect(canDecideRecommendations()).toBe(false)
    await expect(decideRecommendation('1', 'acceptee')).rejects.toThrow('US7')
  })
})
