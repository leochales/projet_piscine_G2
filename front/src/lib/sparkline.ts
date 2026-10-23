export interface Point {
  x: number
  y: number
}

/**
 * Écart minimal représenté sur toute la hauteur, en part de la plus haute valeur. Sans lui,
 * une série presque constante (0,1 % de variation) remplirait toute la hauteur et paraîtrait
 * fluctuer fortement : sous ce seuil, elle reste presque plate, centrée.
 */
export const MIN_RELATIVE_RANGE = 0.15

/**
 * Points d'une mini-courbe : les valeurs occupent la hauteur de la plus basse à la plus haute
 * (c'est la forme qui compte, pas l'échelle), sans exagérer les petits écarts. Une marge évite
 * que le trait soit coupé en haut et en bas.
 */
export function sparklinePoints(
  values: readonly number[],
  width: number,
  height: number,
  margin = 2,
): Point[] {
  if (values.length < 2) return []
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = Math.max(max - min, Math.abs(max) * MIN_RELATIVE_RANGE)
  const bottom = (min + max) / 2 - range / 2 // série centrée dans l'écart retenu
  const step = width / (values.length - 1)
  const inner = height - 2 * margin
  return values.map((v, i) => ({
    x: i * step,
    y: range === 0 ? height / 2 : margin + inner - ((v - bottom) / range) * inner,
  }))
}

/** Tracé SVG (attribut d) d'une suite de points */
export const sparklinePath = (points: readonly Point[]) =>
  points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')

/** Description d'une mini-courbe pour les lecteurs d'écran : « de 3 100 kW à 3 840 kW, … » */
export function describeSeries(values: readonly number[], format: (v: number) => string) {
  if (values.length < 2) return ''
  const first = values[0]!
  const last = values[values.length - 1]!
  return `de ${format(first)} à ${format(last)}, au plus haut ${format(Math.max(...values))}`
}
