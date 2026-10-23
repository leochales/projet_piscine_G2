import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

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

  // La boîte de confirmation est rendue dans <body> (portail) : on la cherche dans le document
  const dialogButton = (label: string) =>
    [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes(label))

  it('demande confirmation, puis émet acknowledge avec l’identifiant de l’alerte', async () => {
    const wrapper = mount(AlertsTable, {
      props: { alerts, canActOn: () => true },
      attachTo: document.body,
    })
    await wrapper.findAll('button')[1]!.trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain('Prendre en compte cette alerte ?')
    expect(document.body.textContent).toContain('SITE003 · Capteur')
    expect(wrapper.emitted('acknowledge')).toBeUndefined()

    dialogButton('Confirmer la prise en compte')!.click()
    await flushPromises()
    expect(wrapper.emitted('acknowledge')).toEqual([['A2']])
    wrapper.unmount()
  })

  it('n’émet rien si on annule', async () => {
    const wrapper = mount(AlertsTable, {
      props: { alerts, canActOn: () => true },
      attachTo: document.body,
    })
    await wrapper.findAll('button')[0]!.trigger('click')
    await flushPromises()

    dialogButton('Annuler')!.click()
    await flushPromises()
    expect(wrapper.emitted('acknowledge')).toBeUndefined()
    expect(document.body.textContent).not.toContain('Prendre en compte cette alerte ?')
    wrapper.unmount()
  })

  it('indique qui a pris l’alerte en compte, et quand', () => {
    const done: Alert = {
      ...alerts[0]!,
      priseEnCompte: true,
      prisePar: 'Léa Bernard',
      priseLe: new Date().toISOString(),
    }
    const wrapper = mount(AlertsTable, { props: { alerts: [done], canActOn: () => true } })
    expect(wrapper.text()).toContain('Prise en compte')
    expect(wrapper.text()).toMatch(/par Léa Bernard, aujourd'hui à \d{2}:\d{2}/)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('bloque le bouton pendant l’envoi de la prise en compte', () => {
    const wrapper = mount(AlertsTable, {
      props: { alerts, canActOn: () => true, pending: new Set(['A1']) },
    })
    const [first, second] = wrapper.findAll('button')
    expect(first!.attributes('disabled')).toBeDefined()
    expect(second!.attributes('disabled')).toBeUndefined()
  })
})
