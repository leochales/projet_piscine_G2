import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import SiteRecommendations from '@/components/site/SiteRecommendations.vue'
import { useRequest } from '@/lib/request'
import { recommandations } from '@/mocks/recommandations'
import { SOURCES } from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'
import { useUserStore } from '@/stores/user'

// Jeton simulé : getJson passe par apiFetch, qui demande le jeton à Keycloak
vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

// Comme la page d'un site (SiteDetailView) : le chargement est fourni au composant.
// Utilisateur gestionnaire par défaut : il peut décider (rôles du jeton Keycloak).
function mountFor(siteId: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useUserStore().setFromToken({ realm_access: { roles: ['GESTION-CLIENT'] } })
  const operations = useOperationsStore()
  const request = useRequest(() => operations.reloadRecommendations())
  return mount(SiteRecommendations, {
    props: { siteId, request },
    global: { plugins: [pinia], stubs: { RouterLink: RouterLinkStub } },
  })
}

const titles = (wrapper: ReturnType<typeof mountFor>) =>
  wrapper.findAll('article h3').map((h) => h.text())

beforeEach(() => {
  SOURCES.recommandations = 'mock'
})

afterEach(() => {
  SOURCES.recommandations = 'api'
  vi.unstubAllGlobals()
})

describe('SiteRecommendations (US5)', () => {
  it('montre les recommandations en cours du site choisi, à décider en premier', async () => {
    const wrapper = mountFor('SITE002')
    await vi.waitFor(() => expect(titles(wrapper).length).toBeGreaterThan(0))

    // La recommandation refusée n'est pas en cours ; celle de SITE006 est sur un autre site
    expect(titles(wrapper)).toEqual([
      'Décaler la ligne de production B de 14 h à 20 h',
      'Couper les compresseurs d’air la nuit',
    ])
  })

  it('indique le site concerné et l’action proposée', async () => {
    const wrapper = mountFor('SITE006')
    await vi.waitFor(() => expect(titles(wrapper)).toHaveLength(1))

    const article = wrapper.get('article')
    expect(article.text()).toContain('Programmer l’arrêt de la climatisation à 22 h')
    expect(article.text()).toContain('SITE006 · Bureaux de Bordeaux')
    expect(article.text()).toContain('gain estimé : 45')
    expect(article.text()).toContain('par semaine')
  })

  it('signale un gain pas encore estimé', async () => {
    const wrapper = mountFor('SITE003')
    await vi.waitFor(() => expect(titles(wrapper)).toHaveLength(1))

    expect(wrapper.get('article').text()).toContain('gain non estimé')
  })

  it('affiche un état vide pour un site sans recommandation en cours', async () => {
    const wrapper = mountFor('SITE005')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Aucune recommandation en cours'))
  })

  it('une recommandation acceptée ici passe en « Acceptée » pour tous les écrans', async () => {
    const wrapper = mountFor('SITE002')
    await vi.waitFor(() => expect(titles(wrapper).length).toBeGreaterThan(0))

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Accepter')!
      .trigger('click')

    const operations = useOperationsStore()
    await vi.waitFor(() =>
      expect(operations.recommendations.find((r) => r.id === '1')?.statut).toBe('acceptee'),
    )
  })

  it('en lecture seule (rôle de consultation), ne propose pas de décider', async () => {
    const wrapper = mountFor('SITE002')
    useUserStore().setFromToken({ realm_access: { roles: ['CONSULT-SITE'] } })
    await vi.waitFor(() => expect(titles(wrapper).length).toBeGreaterThan(0))

    expect(wrapper.findAll('button').map((b) => b.text())).not.toContain('Accepter')
  })

  it('avec les vraies données, propose de décider (route POST de l’US7)', async () => {
    SOURCES.recommandations = 'api'
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(async (url) => {
        const statut = new URL(String(url), 'http://test').searchParams.get('statut')
        const lignes = recommandations.filter((r) => r.statut === statut)
        return new Response(JSON.stringify(lignes), { status: 200 })
      }),
    )

    const wrapper = mountFor('SITE002')
    await vi.waitFor(() => expect(titles(wrapper).length).toBeGreaterThan(0))

    expect(wrapper.findAll('button').map((b) => b.text())).toContain('Accepter')
  })

  it('garde la liste affichée pendant un rafraîchissement en échec', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const operations = useOperationsStore()
    const request = useRequest(() => operations.reloadRecommendations())
    const wrapper = mount(SiteRecommendations, {
      props: { siteId: 'SITE002', request },
      global: { plugins: [pinia], stubs: { RouterLink: RouterLinkStub } },
    })
    await vi.waitFor(() => expect(titles(wrapper).length).toBeGreaterThan(0))

    SOURCES.recommandations = 'api'
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 503 })),
    )
    await request.reload()

    expect(request.status.value).toBe('error')
    expect(titles(wrapper).length).toBeGreaterThan(0)
    expect(wrapper.text()).not.toContain('Impossible de charger')
  })
})
