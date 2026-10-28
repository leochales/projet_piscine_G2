import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'

import { SOURCES } from '@/services/dashboard'
import AlertsView from '@/views/AlertsView.vue'

beforeEach(() => {
  SOURCES.alertes = 'mock'
})

afterEach(() => {
  SOURCES.alertes = 'api'
})

async function mountView() {
  const wrapper = mount(AlertsView, {
    global: { plugins: [createPinia()], stubs: { RouterLink: RouterLinkStub } },
  })
  // Le service simulé répond après un court délai
  await vi.waitFor(() => expect(wrapper.findAll('tbody tr').length).toBeGreaterThan(0))
  return wrapper
}

// Identifiant du site de chaque ligne (la cellule montre aussi le nom du site)
const rows = (wrapper: Awaited<ReturnType<typeof mountView>>) =>
  wrapper.findAll('tbody tr').map((tr) => tr.findAll('td')[1]!.find('span').text())

describe('AlertsView : recommandations', () => {
  it('relie chaque recommandation à la page de son site', async () => {
    const wrapper = await mountView()
    await vi.waitFor(() => expect(wrapper.findAll('article').length).toBeGreaterThan(0))

    const lien = wrapper.findAllComponents(RouterLinkStub)[0]!
    expect(lien.props('to')).toEqual({ name: 'sites', params: { siteId: 'SITE002' } })
    expect(lien.text()).toBe('SITE002 · Usine de Lyon')
  })
})

describe('AlertsView : filtres', () => {
  it('filtre les alertes par gravité, puis par site, et compte les résultats', async () => {
    const wrapper = await mountView()
    expect(rows(wrapper)).toHaveLength(5)

    await wrapper
      .findAll('[role="radio"], button')
      .find((b) => b.text() === 'moyenne')!
      .trigger('click')
    expect(rows(wrapper)).toEqual(['SITE005', 'SITE003', 'SITE004'])
    expect(wrapper.text()).toContain('3 alertes sur 5')

    await wrapper.get('select#filtre-site').setValue('SITE004')
    expect(rows(wrapper)).toEqual(['SITE004'])
    expect(wrapper.text()).toContain('1 alerte sur 5')
  })

  it('propose d’effacer les filtres quand aucune alerte ne correspond', async () => {
    const wrapper = await mountView()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'critique')!
      .trigger('click')
    await wrapper.get('select#filtre-site').setValue('SITE006')

    expect(wrapper.text()).toContain('Aucune alerte ne correspond aux filtres')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Effacer les filtres')!
      .trigger('click')
    expect(rows(wrapper)).toHaveLength(5)
  })
})
