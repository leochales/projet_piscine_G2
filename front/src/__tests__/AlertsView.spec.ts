import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'

import AlertsView from '@/views/AlertsView.vue'

async function mountView() {
  const wrapper = mount(AlertsView, { global: { plugins: [createPinia()] } })
  // Le service simulé répond après un court délai
  await vi.waitFor(() => expect(wrapper.findAll('tbody tr').length).toBeGreaterThan(0))
  return wrapper
}

const rows = (wrapper: Awaited<ReturnType<typeof mountView>>) =>
  wrapper.findAll('tbody tr').map((tr) => tr.findAll('td')[1]!.text())

describe('AlertsView : filtres', () => {
  it('filtre les alertes par gravité, puis par site, et compte les résultats', async () => {
    const wrapper = await mountView()
    expect(rows(wrapper)).toHaveLength(4)

    await wrapper
      .findAll('[role="radio"], button')
      .find((b) => b.text() === 'moyenne')!
      .trigger('click')
    expect(rows(wrapper)).toEqual(['SITE003', 'SITE004'])
    expect(wrapper.text()).toContain('2 alertes sur 4')

    await wrapper.get('select#filtre-site').setValue('SITE004')
    expect(rows(wrapper)).toEqual(['SITE004'])
    expect(wrapper.text()).toContain('1 alerte sur 4')
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
    expect(rows(wrapper)).toHaveLength(4)
  })
})
