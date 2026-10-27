import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import TransmissionBanner from '@/components/overview/TransmissionBanner.vue'
import ConsumptionChart from '@/components/site/ConsumptionChart.vue'
import SiteTransmission from '@/components/site/SiteTransmission.vue'
import { describeSensors, toSiteStatus, transmissionSummary, upcomingRecovery } from '@/lib/etat'
import type { EtatSiteApi } from '@/types/api'
import type { SiteStatus } from '@/types/energy'

// US4 : être averti quand un capteur ou un site ne transmet plus

const etat = (champs: Partial<EtatSiteApi> = {}): EtatSiteApi => ({
  id_site: 'SITE001',
  nom: 'Siège de Paris',
  derniere_mesure_le: '2026-10-27T09:05:00Z',
  collecte_a_jour: true,
  transmet: true,
  etat_capteurs: 'ok',
  capteurs_en_panne: [],
  retablissement_prevu: null,
  ...champs,
})

const statut = (champs: Partial<EtatSiteApi> = {}): SiteStatus => toSiteStatus(etat(champs))

describe('état des sites', () => {
  it('traduit la transmission et les capteurs renvoyés par l’API', () => {
    expect(
      toSiteStatus(
        etat({ transmet: false, etat_capteurs: 'critical', capteurs_en_panne: ['network'] }),
      ),
    ).toEqual({
      siteId: 'SITE001',
      nomSite: 'Siège de Paris',
      transmission: 'muet',
      derniereMesureLe: '2026-10-27T09:05:00Z',
      capteursEnPanne: ['reseau'],
      etatCapteurs: 'critique',
      retablissementPrevu: null,
    })
    expect(statut().transmission).toBe('ok')
    expect(statut({ transmet: null, collecte_a_jour: false }).transmission).toBe('inconnu')
    expect(statut({ etat_capteurs: null }).etatCapteurs).toBeNull()
  })

  it('liste les sites qui ne transmettent plus', () => {
    const resume = transmissionSummary([statut(), statut({ id_site: 'SITE003', transmet: false })])
    expect(resume.collecteArretee).toBe(false)
    expect(resume.sitesMuets.map((s) => s.siteId)).toEqual(['SITE003'])
  })

  it('n’accuse pas les sites quand notre collecte est arrêtée', () => {
    const resume = transmissionSummary([
      statut({ transmet: null, collecte_a_jour: false }),
      statut({ id_site: 'SITE003', transmet: null, collecte_a_jour: false }),
    ])
    expect(resume.collecteArretee).toBe(true)
    expect(resume.sitesMuets).toEqual([])
  })

  it('ne signale rien sans site', () => {
    expect(transmissionSummary([])).toEqual({ collecteArretee: false, sitesMuets: [] })
  })

  it('n’annonce que les rétablissements encore à venir', () => {
    const now = new Date('2026-10-27T10:00:00Z')
    expect(upcomingRecovery(statut({ retablissement_prevu: '2026-10-27T10:30:00Z' }), now)).toBe(
      '2026-10-27T10:30:00Z',
    )
    expect(
      upcomingRecovery(statut({ retablissement_prevu: '2026-10-27T09:30:00Z' }), now),
    ).toBeNull()
    expect(upcomingRecovery(statut(), now)).toBeNull()
  })

  it('nomme les capteurs en panne', () => {
    expect(describeSensors(['reseau', 'temperature'])).toBe('réseau, température')
  })
})

describe('bandeau du dashboard', () => {
  it('signale les sites qui ne transmettent plus et ouvre leur page', async () => {
    const wrapper = mount(TransmissionBanner, {
      props: {
        statuses: [
          statut(),
          statut({ id_site: 'SITE003', nom: 'Data center de Lille', transmet: false }),
        ],
      },
    })
    expect(wrapper.text()).toContain('1 site ne transmet plus')
    expect(wrapper.text()).toContain('SITE003 · Data center de Lille')

    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['SITE003']])
  })

  it('accorde le nombre de sites', () => {
    const wrapper = mount(TransmissionBanner, {
      props: {
        statuses: [statut({ transmet: false }), statut({ id_site: 'SITE003', transmet: false })],
      },
    })
    expect(wrapper.text()).toContain('2 sites ne transmettent plus')
  })

  it('signale une collecte arrêtée sans mettre en cause les sites', () => {
    const wrapper = mount(TransmissionBanner, {
      props: { statuses: [statut({ transmet: null, collecte_a_jour: false })] },
    })
    expect(wrapper.text()).toContain('La collecte des mesures est interrompue')
    expect(wrapper.text()).not.toContain('ne transmet plus')
  })

  it('n’affiche rien quand tous les sites transmettent', () => {
    const wrapper = mount(TransmissionBanner, { props: { statuses: [statut()] } })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})

describe('page du site', () => {
  it('signale un site qui ne transmet plus', () => {
    const wrapper = mount(SiteTransmission, { props: { status: statut({ transmet: false }) } })
    expect(wrapper.text()).toContain('Le site ne transmet plus')
    expect(wrapper.text()).toContain('Dernière mesure reçue')
  })

  it('signale un capteur en panne et son rétablissement prévu', () => {
    const wrapper = mount(SiteTransmission, {
      props: {
        status: statut({
          etat_capteurs: 'degraded',
          capteurs_en_panne: ['temperature'],
          retablissement_prevu: new Date(Date.now() + 3600_000).toISOString(),
        }),
      },
    })
    expect(wrapper.text()).toContain('Capteur en panne : température.')
    expect(wrapper.text()).toContain('Rétablissement prévu')
  })

  it('signale une collecte arrêtée sans mettre le site en cause', () => {
    const wrapper = mount(SiteTransmission, {
      props: { status: statut({ transmet: null, collecte_a_jour: false }) },
    })
    expect(wrapper.text()).toContain('La collecte des mesures est interrompue')
    expect(wrapper.text()).not.toContain('Le site ne transmet plus')
  })

  it('tait un rétablissement déjà passé', () => {
    const wrapper = mount(SiteTransmission, {
      props: {
        status: statut({
          capteurs_en_panne: ['temperature'],
          retablissement_prevu: new Date(Date.now() - 60_000).toISOString(),
        }),
      },
    })
    expect(wrapper.text()).toContain('Capteur en panne : température.')
    expect(wrapper.text()).not.toContain('Rétablissement prévu')
  })

  it('ne montre pas un état des capteurs périmé quand la collecte est arrêtée', () => {
    const wrapper = mount(SiteTransmission, {
      props: {
        status: statut({
          transmet: null,
          collecte_a_jour: false,
          capteurs_en_panne: ['temperature'],
        }),
      },
    })
    expect(wrapper.text()).toContain('La collecte des mesures est interrompue')
    expect(wrapper.text()).not.toContain('en panne')
  })

  it('n’affiche rien quand tout fonctionne', () => {
    const wrapper = mount(SiteTransmission, { props: { status: statut() } })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})

describe('courbe de consommation', () => {
  const series = (minutesImputees: number) => ({
    mesures: [
      { horodatage: '2026-10-27T08:00:00Z', kw: 500, kwh: 500, coutEur: 70, minutesImputees },
    ],
    predictions: [],
  })

  it('légende les heures reconstituées après une panne', () => {
    const wrapper = mount(ConsumptionChart, { props: { series: series(15), capaciteKw: 1000 } })
    expect(wrapper.text()).toContain('heure en partie reconstituée après une panne')
  })

  it('ne marque pas quelques minutes isolées reconstituées', () => {
    const wrapper = mount(ConsumptionChart, { props: { series: series(14), capaciteKw: 1000 } })
    expect(wrapper.text()).not.toContain('reconstituée')
  })

  it('ne légende rien sans valeur reconstituée', () => {
    const wrapper = mount(ConsumptionChart, { props: { series: series(0), capaciteKw: 1000 } })
    expect(wrapper.text()).not.toContain('reconstituée')
  })
})
