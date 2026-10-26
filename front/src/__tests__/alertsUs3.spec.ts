import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import AlertsTable from '@/components/alerts/AlertsTable.vue'
import SiteAlerts from '@/components/site/SiteAlerts.vue'
import { thresholdText, toAlert } from '@/lib/alerts'
import { useRequest } from '@/lib/request'
import { alertes } from '@/mocks/alertes'
import { acknowledgeAlert, canAcknowledgeAlerts, fetchAlerts, SOURCES } from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'
import { useUserStore } from '@/stores/user'
import type { AlerteApi } from '@/types/api'

// Jeton simulé : getJson passe par apiFetch, qui demande le jeton à Keycloak
vi.mock('@/lib/auth', () => ({
  getToken: vi.fn<() => Promise<string>>(() => Promise.resolve('jeton-de-test')),
  login: vi.fn<() => Promise<void>>(() => Promise.resolve()),
}))

const depassement: AlerteApi = {
  id_alerte: 42,
  id_site: 'SITE005',
  nom_site: 'Entrepôt de Rennes',
  source: 'etl',
  type: 'threshold',
  severite: 'high',
  message: null,
  debut: '2026-10-26T13:00:00Z',
  fin: null,
  valeur: 752,
  seuil: 720,
  prise_en_compte: false,
  prise_par: null,
  prise_le: null,
}

afterEach(() => {
  SOURCES.alertes = 'mock'
  vi.unstubAllGlobals()
})

describe('toAlert (GET /api/alertes)', () => {
  it('convertit un dépassement de seuil : site, heure, mesure et seuil', () => {
    expect(toAlert(depassement)).toEqual({
      id: '42',
      siteId: 'SITE005',
      nomSite: 'Entrepôt de Rennes',
      type: 'threshold',
      gravite: 'critique', // « high » : traité comme critique (3 niveaux dans le dashboard)
      message: 'Dépassement du seuil de consommation',
      debut: '2026-10-26T13:00:00Z',
      valeurKw: 752,
      seuilKw: 720,
      priseEnCompte: false,
      priseLe: undefined,
    })
  })

  it('garde le message de l’API quand il existe', () => {
    expect(toAlert({ ...depassement, message: 'Seuil dépassé ligne B' }).message).toBe(
      'Seuil dépassé ligne B',
    )
  })

  it('ne montre pas l’identifiant Keycloak de la personne qui a pris l’alerte en compte', () => {
    const prise = toAlert({
      ...depassement,
      prise_en_compte: true,
      prise_par: '3f1c2a9e-7b4d-4e21-9c55-2d6b8a0f1e77',
      prise_le: '2026-10-26T14:00:00Z',
    })
    expect(prise.prisePar).toBeUndefined()
    expect(prise.priseLe).toBe('2026-10-26T14:00:00Z')
  })

  it('accepte toutes les alertes simulées (même format que l’API)', () => {
    expect(alertes.map(toAlert)).toHaveLength(alertes.length)
  })
})

describe('thresholdText', () => {
  it('compare la mesure au seuil, avec l’écart en %', () => {
    expect(thresholdText(toAlert(depassement))).toMatch(
      /^752 kW pour un seuil de 720 kW \(\+4 %\)$/u,
    )
  })

  it('rien sans mesure ou sans seuil', () => {
    expect(thresholdText(toAlert({ ...depassement, valeur: null }))).toBeNull()
    expect(thresholdText(toAlert({ ...depassement, seuil: null }))).toBeNull()
  })
})

describe('AlertsTable : dépassement de seuil (US3)', () => {
  it('indique le site, l’heure et la valeur mesurée', () => {
    const wrapper = mount(AlertsTable, {
      props: { alerts: [toAlert(depassement)], canActOn: () => false },
    })
    const texte = wrapper.text()

    expect(texte).toContain('SITE005')
    expect(texte).toContain('Entrepôt de Rennes')
    expect(texte).toContain('Dépassement du seuil de consommation')
    expect(wrapper.get('time').attributes('datetime')).toBe('2026-10-26T13:00:00Z')
    expect(texte).toMatch(/752 kW pour un seuil de 720 kW/u)
  })

  it('une prise en compte venue de l’API affiche sa date, sans nom', () => {
    const prise = toAlert({
      ...depassement,
      prise_en_compte: true,
      prise_par: '3f1c2a9e-7b4d-4e21-9c55-2d6b8a0f1e77',
      prise_le: new Date().toISOString(),
    })
    const wrapper = mount(AlertsTable, { props: { alerts: [prise], canActOn: () => true } })

    expect(wrapper.text()).toMatch(/Prise en compte\s*aujourd'hui à \d{2}:\d{2}/u)
    expect(wrapper.text()).not.toContain('3f1c2a9e')
  })
})

describe('source des alertes : données simulées ou API', () => {
  it('avec la source « api », lit GET /api/alertes en cours, avec le jeton', async () => {
    SOURCES.alertes = 'api'
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify([depassement]), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const liste = await fetchAlerts()

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/alertes?en_cours=true&limite=500')
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer jeton-de-test')
    expect(liste).toEqual([expect.objectContaining({ id: '42', type: 'threshold' })])
  })

  it('avec les vraies données, la prise en compte est bloquée tant qu’elle ne peut être enregistrée (US7)', async () => {
    expect(canAcknowledgeAlerts()).toBe(true)
    SOURCES.alertes = 'api'
    expect(canAcknowledgeAlerts()).toBe(false)
    await expect(acknowledgeAlert('42')).rejects.toThrow('US7')
  })
})

describe('SiteAlerts : alertes du site choisi (US3)', () => {
  function mountFor(siteId: string, roles = ['GESTION-CLIENT']) {
    const pinia = createPinia()
    setActivePinia(pinia)
    useUserStore().setFromToken({ realm_access: { roles } })
    const operations = useOperationsStore()
    const request = useRequest(() => operations.reloadAlerts())
    return mount(SiteAlerts, { props: { siteId, request }, global: { plugins: [pinia] } })
  }

  it('montre le dépassement de seuil du site, visible par tous ceux qui le consultent', async () => {
    // Rôle de consultation : il voit l'alerte, sans pouvoir la prendre en compte
    const wrapper = mountFor('SITE005', ['CONSULT-SITE'])
    await vi.waitFor(() => expect(wrapper.findAll('tbody tr')).toHaveLength(1))

    expect(wrapper.text()).toContain('Dépassement du seuil de consommation')
    expect(wrapper.text()).toMatch(/752 kW pour un seuil de 720 kW/u)
    expect(wrapper.findAll('button').map((b) => b.text())).not.toContain('Prise en compte')
  })

  it('n’affiche que les alertes du site', async () => {
    const wrapper = mountFor('SITE003')
    await vi.waitFor(() => expect(wrapper.findAll('tbody tr')).toHaveLength(1))
    expect(wrapper.text()).toContain('Capteur en panne')
    expect(wrapper.text()).not.toContain('SITE005')
  })

  it('affiche un état vide pour un site sans alerte en cours', async () => {
    const wrapper = mountFor('SITE001')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Aucune alerte en cours'))
  })

  it('une prise en compte reste visible après un rafraîchissement des alertes', async () => {
    const wrapper = mountFor('SITE005')
    await vi.waitFor(() => expect(wrapper.findAll('tbody tr')).toHaveLength(1))
    const operations = useOperationsStore()

    await operations.acknowledge('5')
    await operations.reloadAlerts() // les données simulées renvoient l'alerte non prise
    await flushPromises()

    expect(operations.alerts.find((a) => a.id === '5')?.priseEnCompte).toBe(true)
  })
})
