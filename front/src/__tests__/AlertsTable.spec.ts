import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import AlertsTable from '@/components/alerts/AlertsTable.vue'
import type { Alert } from '@/types/energy'

const alerts: Alert[] = [
  { id: 'A1', siteId: 'SITE002', gravite: 'critique', message: 'Pic prévu', priseEnCompte: false },
  { id: 'A2', siteId: 'SITE003', gravite: 'moyenne', message: 'Capteur', priseEnCompte: false },
]

describe('AlertsTable', () => {
  it('ne montre le bouton que pour les sites autorisés', () => {
    const wrapper = mount(AlertsTable, {
      props: { alerts, canActOn: (siteId: string) => siteId === 'SITE002' },
    })
    expect(wrapper.findAll('button')).toHaveLength(1)
  })

  it('émet acknowledge avec l’identifiant de l’alerte', async () => {
    const wrapper = mount(AlertsTable, { props: { alerts, canActOn: () => true } })
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(wrapper.emitted('acknowledge')).toEqual([['A2']])
  })
})
