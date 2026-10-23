import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import SitesTable from '@/components/overview/SitesTable.vue'
import router from '@/router'
import { overview } from '@/mocks/data'

const mountTable = () =>
  mount(SitesTable, { props: { rows: overview }, global: { plugins: [router] } })

// Lignes du tableau (hors en-tête), dans l'ordre affiché
const tableIds = (wrapper: ReturnType<typeof mountTable>) =>
  wrapper.findAll('table tbody tr').map((tr) => tr.find('td').text())
const lastTableId = (wrapper: ReturnType<typeof mountTable>) => {
  const ids = tableIds(wrapper)
  return ids[ids.length - 1]
}

describe('SitesTable', () => {
  it('trie la colonne cliquée, du plus chargé au moins chargé, puis dans l’autre sens', async () => {
    const wrapper = mountTable()
    const header = wrapper.findAll('th').find((th) => th.text().includes('% de la capacité'))!
    expect(header.attributes('aria-sort')).toBe('none')

    await header.find('button').trigger('click')
    expect(header.attributes('aria-sort')).toBe('descending')
    expect(tableIds(wrapper)[0]).toBe('SITE002') // 86 %, le plus chargé
    expect(lastTableId(wrapper)).toBe('SITE003') // sans mesure

    await header.find('button').trigger('click')
    expect(header.attributes('aria-sort')).toBe('ascending')
    expect(lastTableId(wrapper)).toBe('SITE003') // toujours en dernier
  })

  it('sur écran étroit, trie avec le menu « Trier par »', async () => {
    const wrapper = mountTable()
    await wrapper.get('select#tri-sites').setValue('consommation')
    const cards = wrapper.findAll('ul li a').map((a) => a.text())
    expect(cards[0]).toBe('SITE002')
  })
})
