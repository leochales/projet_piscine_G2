import { describe, expect, it } from 'vitest'

import { hoursBetween, predictedPeak } from '@/lib/predictions'
import type { PredictionPoint } from '@/types/energy'

const heure = (horodatage: string, valeurs: Partial<PredictionPoint> = {}): PredictionPoint => ({
  horodatage,
  kw: 100,
  basseKw: 90,
  hauteKw: 110,
  picKw: null,
  picBasKw: null,
  picHautKw: null,
  ...valeurs,
})

describe('lib/predictions', () => {
  it('prend le maximum de l’heure quand le modèle le donne', () => {
    // La 2e heure a une moyenne plus basse, mais une pointe plus haute : c'est elle le pic
    const peak = predictedPeak([
      heure('2026-10-28T12:00:00Z', { kw: 500, picKw: 520, picBasKw: 500, picHautKw: 540 }),
      heure('2026-10-28T13:00:00Z', { kw: 480, picKw: 610, picBasKw: 580, picHautKw: 650 }),
    ])

    expect(peak).toEqual({
      horodatage: '2026-10-28T13:00:00Z',
      kw: 610,
      basseKw: 580,
      hauteKw: 650,
      mesure: 'maximum',
    })
  })

  it('prend la moyenne horaire quand le maximum n’est pas prévu', () => {
    const peak = predictedPeak([
      heure('2026-10-28T12:00:00Z', { kw: 500 }),
      heure('2026-10-28T13:00:00Z', { kw: 520, basseKw: null, hauteKw: null }),
    ])

    expect(peak).toEqual({
      horodatage: '2026-10-28T13:00:00Z',
      kw: 520,
      basseKw: null,
      hauteKw: null,
      mesure: 'moyenne',
    })
  })

  it('ne donne pas de pic sans prévision', () => {
    expect(predictedPeak([])).toBeNull()
  })

  it('garde l’heure en cours entre la dernière mesure et la première prévision', () => {
    expect(hoursBetween('2026-10-28T12:00:00Z', '2026-10-28T14:00:00Z')).toEqual([
      '2026-10-28T13:00:00.000Z',
    ])
    // Heures qui se suivent : rien à ajouter
    expect(hoursBetween('2026-10-28T12:00:00Z', '2026-10-28T13:00:00Z')).toEqual([])
  })

  it('n’ajoute pas plus de 7 jours d’heures vides', () => {
    expect(hoursBetween('2026-01-01T00:00:00Z', '2026-12-01T00:00:00Z')).toHaveLength(7 * 24)
  })
})
