import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

import App from '../App.vue'
import router from '../router'

describe('App', () => {
  it("affiche la navigation et la vue d'ensemble", async () => {
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Alertes et recommandations')
    expect(wrapper.text()).toContain("Vue d'ensemble du parc")
    expect(wrapper.text()).toContain('Responsable énergie')
  })

  it('affiche dans le menu le nombre d’alertes à traiter, dont les critiques', async () => {
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    // Données de démonstration : 3 alertes à traiter, dont 1 critique
    const nav = wrapper.get('nav[aria-label="Navigation principale"]')
    // Le service simulé répond après un court délai
    await vi.waitFor(() => expect(nav.text()).toContain('3 à traiter, dont 1 critique'))
  })

  it('affiche une page introuvable pour une adresse inconnue, sans renvoyer à l’accueil', async () => {
    await router.push('/nimporte/quoi')

    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/nimporte/quoi')
    expect(wrapper.text()).toContain('Page introuvable')
    expect(wrapper.text()).toContain('/nimporte/quoi')
    expect(document.title).toBe('Page introuvable · EnerVision')
  })
})
