import { describe, expect, it } from 'vitest'

import {
  costsFrom,
  fleetFrom,
  isReliableHour,
  junctionIndex,
  kpisFrom,
  parisMidnight,
  toConsumptionPoint,
  toSiteOverview,
} from '@/lib/mesures'
import type { ConsommationHoraireApi, DerniereMesureApi } from '@/types/api'

const mesure = (partiel: Partial<DerniereMesureApi> = {}): DerniereMesureApi => ({
  id_site: 'SITE002',
  nom: 'Usine Lyon Vénissieux',
  type: 'factory',
  capacite_kw: 1000,
  horodatage: '2026-10-27T09:05:00Z',
  consommation_kw: 640,
  data_quality: 'good',
  ...partiel,
})

describe('dernière mesure', () => {
  it('reprend le site, la puissance et l’heure', () => {
    expect(toSiteOverview(mesure())).toMatchObject({
      site: { id: 'SITE002', nom: 'Usine Lyon Vénissieux', type: 'usine', capaciteKw: 1000 },
      consommationKw: 640,
      mesureLe: '2026-10-27T09:05:00Z',
      picPrevu: null,
      qualite: { statut: 'bonne' },
    })
  })

  it('traduit les types de site et la qualité renvoyés par l’API', () => {
    expect(toSiteOverview(mesure({ type: 'retail' })).site.type).toBe('commerce')
    expect(toSiteOverview(mesure({ type: 'datacenter' })).site.type).toBe('data_center')
    expect(toSiteOverview(mesure({ data_quality: 'partial' })).qualite).toEqual({
      statut: 'partielle',
    })
    expect(toSiteOverview(mesure({ data_quality: 'critical' })).qualite).toEqual({
      statut: 'mauvaise',
    })
    expect(toSiteOverview(mesure({ type: 'serre' })).site.type).toBe('serre')
  })

  it('garde une puissance absente : un capteur en panne n’affiche pas 0 kW', () => {
    expect(toSiteOverview(mesure({ consommation_kw: null })).consommationKw).toBeNull()
  })
})

describe('consommation horaire', () => {
  const heure = (
    h: string,
    kwh: number | null,
    cout: number | null,
    nbImputees = 0,
  ): ConsommationHoraireApi => ({
    heure: h,
    consommation_kwh: kwh,
    cout_eur: cout,
    nb_imputees: nbImputees,
    taux_couverture: kwh === null ? 0 : 1,
  })

  it('reprend les kWh et le coût, et garde une heure sans mesure', () => {
    expect(toConsumptionPoint(heure('2026-10-27T08:00:00Z', 500, 70))).toEqual({
      horodatage: '2026-10-27T08:00:00Z',
      kw: 500,
      kwh: 500,
      coutEur: 70,
      minutesImputees: 0,
      couverture: 1,
    })
    expect(toConsumptionPoint(heure('2026-10-27T09:00:00Z', null, null))).toEqual({
      horodatage: '2026-10-27T09:00:00Z',
      kw: null,
      kwh: null,
      coutEur: null,
      minutesImputees: 0,
      couverture: 0,
    })
  })

  it('garde le nombre de minutes reconstituées après une panne (US4)', () => {
    expect(toConsumptionPoint(heure('2026-10-27T08:00:00Z', 480, 67.2, 12)).minutesImputees).toBe(
      12,
    )
  })

  it('additionne le coût et le CO₂ des heures reçues', () => {
    const rows = [heure('2026-10-27T08:00:00Z', 100, 14), heure('2026-10-27T09:00:00Z', null, null)]
    expect(costsFrom(rows)).toEqual({ coutEur: 14, co2Tonnes: (100 * 0.052) / 1000 })
  })

  it('situe minuit à Paris, y compris le jour du changement d’heure', () => {
    // 27 octobre 2026, 10:00 UTC = 11:00 à Paris (UTC+1, heure d'hiver)
    const hiver = new Date('2026-10-27T10:00:00Z')
    expect(parisMidnight(0, hiver).toISOString()).toBe('2026-10-26T23:00:00.000Z')
    expect(parisMidnight(-1, hiver).toISOString()).toBe('2026-10-25T23:00:00.000Z')
    // 29 mars 2026 : midi est déjà à l'heure d'été, minuit est encore à l'heure d'hiver
    expect(parisMidnight(0, new Date('2026-03-29T12:00:00Z')).toISOString()).toBe(
      '2026-03-28T23:00:00.000Z',
    )
    // 25 octobre 2026 : midi est déjà à l'heure d'hiver, minuit est encore à l'heure d'été
    expect(parisMidnight(0, new Date('2026-10-25T12:00:00Z')).toISOString()).toBe(
      '2026-10-24T22:00:00.000Z',
    )
  })

  it('compare les heures closes d’aujourd’hui aux mêmes heures hier', () => {
    const now = new Date('2026-10-27T10:30:00Z') // 11:30 à Paris : l'heure 11 est encore ouverte
    const sites = [
      toSiteOverview(mesure()),
      toSiteOverview(mesure({ id_site: 'SITE003', consommation_kw: null })),
    ]
    const heures = [
      heure('2026-10-25T23:00:00Z', 10, 1), // hier 0 h
      heure('2026-10-26T09:00:00Z', 10, 4), // hier 10 h
      heure('2026-10-26T10:00:00Z', 10, 9), // hier 11 h : l'heure en cours, écartée des deux côtés
      heure('2026-10-26T23:00:00Z', 10, 2), // aujourd'hui 0 h
      heure('2026-10-27T09:00:00Z', 10, 3), // aujourd'hui 10 h
    ]
    const kpis = kpisFrom(sites, heures, now)
    expect(kpis.nbSites).toBe(2)
    expect(kpis.nbSitesSansMesure).toBe(1)
    expect(kpis.consommationKw).toBe(640)
    expect(kpis.coutJourEur).toBe(5)
    // Hier sur les heures closes : 1 + 4, pas le 9 de l'heure encore ouverte
    expect(kpis.variationCoutPct).toBeCloseTo(0)
  })

  it('aligne hier sur la même heure civile le lendemain d’un changement d’heure', () => {
    // 30 mars 2026, 08:30 UTC = 10:30 à Paris. Le 29, 10 h locales valent 08:00 UTC,
    // pas 09:00 : hier a duré 23 h, une durée égale décalerait la fenêtre d'une heure.
    const now = new Date('2026-03-30T08:30:00Z')
    const heures = [
      heure('2026-03-29T07:00:00Z', 10, 4), // hier 9 h
      heure('2026-03-29T08:00:00Z', 10, 9), // hier 10 h, heure encore ouverte aujourd'hui
      heure('2026-03-29T22:00:00Z', 10, 2), // aujourd'hui 0 h
      heure('2026-03-30T07:00:00Z', 10, 3), // aujourd'hui 9 h
    ]
    const kpis = kpisFrom([toSiteOverview(mesure())], heures, now)
    expect(kpis.coutJourEur).toBe(5)
    expect(kpis.variationCoutPct).toBeCloseTo(((5 - 4) / 4) * 100)
  })

  it('regroupe la courbe 24 h et les 7 coûts journaliers', () => {
    const now = new Date('2026-10-27T10:00:00Z')
    const trend = fleetFrom(
      [
        heure('2026-10-26T11:00:00Z', 10, 1), // dans les 24 h
        heure('2026-10-26T11:00:00Z', 5, 1), // même heure, autre site
        heure('2026-10-26T12:00:00Z', 8, 1),
        heure('2026-10-26T12:00:00Z', null, null), // un site sans mesure : trou, pas une chute
        heure('2026-10-20T23:00:00Z', 100, 8), // 21 octobre, trop ancien pour la courbe
        heure('2026-10-26T23:00:00Z', 20, 4), // aujourd'hui 0 h
      ],
      now,
    )
    expect(trend.consommationKw24h).toEqual([15, null, 20])
    expect(trend.coutEurJours7).toHaveLength(7)
    expect(trend.coutEurJours7[0]).toBe(8)
    expect(trend.coutEurJours7[6]).toBe(4)
  })
})

describe('départ de la courbe prévue', () => {
  const point = (kw: number | null, couverture?: number, minutesImputees = 0) => ({
    horodatage: '2026-10-28T12:00:00Z',
    kw,
    couverture,
    minutesImputees,
  })

  it('part de la dernière heure bien mesurée', () => {
    // Dernière heure : 10 minutes mesurées pendant une panne, sa moyenne chute
    expect(junctionIndex([point(490, 1), point(495, 1), point(422, 10 / 60)])).toBe(1)
  })

  it('écarte une heure surtout reconstituée', () => {
    expect(junctionIndex([point(490, 1), point(430, 1, 40)])).toBe(0)
  })

  it('garde la dernière valeur si aucune heure n’est bien mesurée', () => {
    expect(junctionIndex([point(null, 0), point(420, 0.2), point(410, 0.1)])).toBe(2)
  })

  it('considère les données simulées, sans couverture, comme fiables', () => {
    expect(junctionIndex([point(490), point(480)])).toBe(1)
    expect(isReliableHour(point(null))).toBe(false)
  })
})
