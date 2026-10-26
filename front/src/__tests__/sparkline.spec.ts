import { describe, expect, it } from 'vitest'

import { describeSeries, sparklinePath, sparklinePoints } from '@/lib/sparkline'

describe('sparklinePoints', () => {
  it('étale les valeurs sur la largeur, et sur toute la hauteur moins la marge', () => {
    const points = sparklinePoints([10, 30, 20], 100, 20, 2)
    expect(points.map((p) => p.x)).toEqual([0, 50, 100])
    // La plus haute valeur en haut (y = marge), la plus basse en bas (y = hauteur − marge)
    expect(points.map((p) => p.y)).toEqual([18, 2, 10])
  })

  it('trace une courbe plate au milieu', () => {
    expect(sparklinePoints([5, 5, 5], 60, 20).map((p) => p.y)).toEqual([10, 10, 10])
    expect(sparklinePoints([0, 0], 60, 20).map((p) => p.y)).toEqual([10, 10])
  })

  it('n’exagère pas une série presque constante', () => {
    // 0,05 % de variation : sans seuil, la courbe irait du bas au haut de la carte
    const ys = sparklinePoints([19748, 19758, 19750], 60, 20).map((p) => p.y)
    expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(0.1)
  })

  it('ne trace rien avec moins de deux valeurs', () => {
    expect(sparklinePoints([], 60, 20)).toEqual([])
    expect(sparklinePoints([42], 60, 20)).toEqual([])
  })
})

describe('sparklinePath', () => {
  it('relie les points, en partant du premier', () => {
    expect(
      sparklinePath([
        { x: 0, y: 18 },
        { x: 50, y: 2.25 },
      ]),
    ).toBe('M0.0 18.0 L50.0 2.3')
    expect(sparklinePath([])).toBe('')
  })
})

describe('describeSeries', () => {
  it('décrit le début, la fin et le maximum, avec le format de l’indicateur', () => {
    expect(describeSeries([3100, 3900, 3840], (v) => `${v} kW`)).toBe(
      'de 3100 kW à 3840 kW, au plus haut 3900 kW',
    )
    expect(describeSeries([1], String)).toBe('')
  })
})
