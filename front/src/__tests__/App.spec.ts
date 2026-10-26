import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'

import App from '../App.vue'
import router from '../router'
import { useUserStore } from '../stores/user'

let pinia: Pinia
let wrapper: VueWrapper | undefined

const mountApp = () => (wrapper = mount(App, { global: { plugins: [pinia, router] } }))

describe('App', () => {
  beforeEach(async () => {
    pinia = createPinia()
    setActivePinia(pinia)
    useUserStore(pinia).setFromToken({
      realm_access: { roles: ['GESTION-CLIENT'] },
      name: 'Camille Martin',
      email: 'camille.martin@client.fr',
    })
    // Le routeur est partagé entre les tests : une page neutre évite qu'une navigation vers la
    // page déjà affichée soit ignorée, sans repasser par la vérification des rôles
    await router.replace('/acces-refuse')
  })

  // Une application restée montée suivrait le routeur partagé avec le store d'un ancien test
  afterEach(() => wrapper?.unmount())

  it("affiche la navigation, la vue d'ensemble et l'utilisateur connecté", async () => {
    await router.push('/')

    const app = mountApp()
    await flushPromises()

    expect(app.text()).toContain('Alertes et recommandations')
    expect(app.text()).toContain("Vue d'ensemble du parc")
    expect(app.text()).toContain('Camille Martin')
  })

  it('affiche dans le menu le nombre d’alertes à traiter, dont les critiques', async () => {
    await router.push('/')

    const app = mountApp()
    await flushPromises()

    // Données de démonstration : 3 alertes à traiter, dont 1 critique
    const nav = app.get('nav[aria-label="Navigation principale"]')
    // Le service simulé répond après un court délai
    await vi.waitFor(() => expect(nav.text()).toContain('3 à traiter, dont 1 critique'))
  })

  it('affiche une page introuvable pour une adresse inconnue, sans renvoyer à l’accueil', async () => {
    await router.push('/nimporte/quoi')

    const app = mountApp()
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/nimporte/quoi')
    expect(app.text()).toContain('Page introuvable')
    expect(app.text()).toContain('/nimporte/quoi')
    expect(document.title).toBe('Page introuvable · EnerVision')
  })

  it('montre l’accès refusé sans navigation à un compte sans accès au dashboard', async () => {
    useUserStore(pinia).setFromToken({ realm_access: { roles: ['MONITORING'] }, email: 'm@b.fr' })
    await router.push('/alertes')

    const app = mountApp()
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('access-denied')
    expect(app.text()).toContain('Accès refusé')
    expect(app.text()).toContain('m@b.fr')
    expect(app.find('nav[aria-label="Navigation principale"] a').exists()).toBe(false)
  })

  it('montre la page du compte non rattaché, sans navigation ni données', async () => {
    const user = useUserStore(pinia)
    user.unlinked = true
    await router.push('/')

    const app = mountApp()
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('unlinked-account')
    expect(app.text()).toContain('Compte non rattaché')
    expect(app.text()).toContain('camille.martin@client.fr')
    // Rôle de gestion, mais aucune entreprise : pas de liens vers les écrans de données
    expect(app.find('nav[aria-label="Navigation principale"] a').exists()).toBe(false)
  })

  it('affiche les liens dès que le compte obtient un rôle du dashboard', async () => {
    const user = useUserStore(pinia)
    user.setFromToken({ realm_access: { roles: ['MONITORING'] }, email: 'm@b.fr' })
    await router.push('/acces-refuse')

    const app = mountApp()
    await flushPromises()
    const nav = () => app.find('nav[aria-label="Navigation principale"]')
    expect(nav().find('a').exists()).toBe(false)

    // Rôle ajouté dans Keycloak, reçu au renouvellement du jeton (onTokenRefresh)
    user.setFromToken({ realm_access: { roles: ['CONSULT-SITE'] }, email: 'm@b.fr' })
    await flushPromises()

    expect(nav().text()).toContain('Alertes et recommandations')
  })
})
