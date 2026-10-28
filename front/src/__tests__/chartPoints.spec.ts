import { describe, expect, it } from 'vitest'

import { buildChartPoints, nowIndexOf, peakOnAxis } from '@/lib/chartPoints'
import type { ConsumptionPoint, PredictionPoint, SiteSeries } from '@/types/energy'

const mesure = (horodatage: string, kw: number | null, couverture = 1): ConsumptionPoint => ({
  horodatage,
  kw,
  kwh: kw,
  coutEur: null,
  minutesImputees: 0,
  couverture,
})

const prevision = (
  horodatage: string,
  valeurs: Partial<PredictionPoint> = {},
): PredictionPoint => ({
  horodatage,
  kw: 500,
  basseKw: 480,
  hauteKw: 520,
  picKw: null,
  picBasKw: null,
  picHautKw: null,
  picPrevu: false,
  ...valeurs,
})

// Il est 13 h 20 : mesures jusqu'à l'heure close de 12 h, prévisions à partir de 14 h
const serie: SiteSeries = {
  mesures: [mesure('2026-10-28T11:00:00Z', 490), mesure('2026-10-28T12:00:00Z', 485)],
  predictions: [
    prevision('2026-10-28T14:00:00Z'),
    prevision('2026-10-28T15:00:00Z', { kw: 530, picKw: 560 }),
  ],
}
const MAINTENANT = new Date('2026-10-28T13:20:00Z').getTime()

describe('axe du graphique', () => {
  it('met les mesures, l’heure en cours vide, puis les prévisions', () => {
    const points = buildChartPoints(serie)

    expect(points.map((p) => p.t)).toEqual([
      '2026-10-28T11:00:00Z',
      '2026-10-28T12:00:00Z',
      '2026-10-28T13:00:00.000Z',
      '2026-10-28T14:00:00Z',
      '2026-10-28T15:00:00Z',
    ])
    // L'heure en cours n'est ni mesurée ni prévue
    expect(points[2]).toMatchObject({ mesure: null, pred: null, basse: null, haute: null })
    expect(points[4]).toMatchObject({ pred: 530, basse: 480, haute: 520, pic: 560 })
  })

  it('fait partir la prévision de la dernière mesure, et d’elle seule', () => {
    const points = buildChartPoints(serie)

    expect(points.map((p) => p.pred)).toEqual([null, 485, null, 500, 530])
    expect(points[1]).toMatchObject({ basse: 485, haute: 485 })
  })

  it('fait partir la prévision de la dernière heure bien mesurée', () => {
    const avecPanne: SiteSeries = {
      ...serie,
      mesures: [mesure('2026-10-28T11:00:00Z', 490), mesure('2026-10-28T12:00:00Z', 130, 0.2)],
    }

    expect(buildChartPoints(avecPanne).map((p) => p.pred)).toEqual([490, null, null, 500, 530])
  })

  it('n’ajoute pas d’heure vide sans prévision', () => {
    const points = buildChartPoints({ ...serie, predictions: [] })

    expect(points).toHaveLength(2)
  })

  it('place « maintenant » dans l’heure en cours', () => {
    const points = buildChartPoints(serie)

    expect(nowIndexOf(points, MAINTENANT)).toBe(2)
    // Une heure plus tard, sans rechargement des données, la ligne avance
    expect(nowIndexOf(points, MAINTENANT + 3_600_000)).toBe(3)
  })

  it('place le rond du pic à son heure, à la valeur du maximum de l’heure', () => {
    const points = buildChartPoints(serie)

    expect(peakOnAxis(points, serie)).toEqual({ index: 4, kw: 560 })
    expect(peakOnAxis(points, { ...serie, predictions: [] })).toBeNull()
  })
})
