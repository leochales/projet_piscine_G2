import { describe, it, expect } from 'vitest'
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
})
