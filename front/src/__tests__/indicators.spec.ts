import { describe, expect, it } from 'vitest'

import {
  capacityLevel,
  capacityPct,
  SEUIL_ALERTE_PCT,
  SEUIL_ELEVE_PCT,
  trend,
} from '@/lib/indicators'

describe('capacité', () => {
  it('calcule la part de la capacité utilisée, ou rien sans mesure', () => {
    expect(capacityPct(1640, 1900)).toBeCloseTo(86.3, 1)
    expect(capacityPct(0, 800)).toBe(0) // site arrêté : 0 %, à ne pas confondre avec « pas de mesure »
    expect(capacityPct(null, 1360)).toBeNull()
  })

  it('met la barre en avant au-dessus de 85 %, en alerte à partir de 90 %', () => {
    expect(capacityLevel(SEUIL_ELEVE_PCT - 0.1)).toBe('normal')
    expect(capacityLevel(SEUIL_ELEVE_PCT)).toBe('eleve')
    expect(capacityLevel(SEUIL_ALERTE_PCT - 0.1)).toBe('eleve')
    expect(capacityLevel(SEUIL_ALERTE_PCT)).toBe('critique')
    expect(capacityLevel(120)).toBe('critique') // dépassement de la capacité
  })

  it('suit le seuil d’alerte du site : 92 % n’est pas critique pour un data center', () => {
    // Data center : seuil à 100 %, charge élevée à partir de 95 %
    expect(capacityLevel(92, 100)).toBe('normal')
    expect(capacityLevel(95, 100)).toBe('eleve')
    expect(capacityLevel(100, 100)).toBe('critique')
  })
})

describe('tendance', () => {
  it('une hausse de coût est défavorable, une baisse favorable', () => {
    expect(trend(4, 'baisse')).toEqual({
      direction: 'hausse',
      favorable: false,
      label: 'en hausse, défavorable',
    })
    expect(trend(-3, 'baisse')).toMatchObject({ direction: 'baisse', favorable: true })
  })

  it('suit le bon sens donné pour un indicateur qu’on veut voir monter', () => {
    expect(trend(12, 'hausse')).toMatchObject({ favorable: true, label: 'en hausse, favorable' })
    expect(trend(-12, 'hausse')).toMatchObject({ favorable: false })
  })

  it('sans variation, ni bonne ni mauvaise nouvelle', () => {
    expect(trend(0, 'baisse')).toEqual({ direction: 'stable', favorable: null, label: 'stable' })
  })
})
