// Règles d'affichage des indicateurs : niveau de la barre de capacité et sens des tendances.
// Chaque niveau se lit aussi sans la couleur (texte, icône, pourcentage).

/** Seuil d'alerte : au-delà, un pic est signalé (alertes, prédictions) */
export const SEUIL_ALERTE_PCT = 90
/** Charge élevée : la barre est mise en avant avant d'atteindre le seuil d'alerte */
export const SEUIL_ELEVE_PCT = 85

export type CapacityLevel = 'normal' | 'eleve' | 'critique'

/** Part de la capacité utilisée, ou null si le site n'a pas de mesure (capteur en panne) */
export function capacityPct(consommationKw: number | null, capaciteKw: number): number | null {
  return consommationKw === null ? null : (consommationKw / capaciteKw) * 100
}

export function capacityLevel(pct: number): CapacityLevel {
  if (pct >= SEUIL_ALERTE_PCT) return 'critique'
  if (pct >= SEUIL_ELEVE_PCT) return 'eleve'
  return 'normal'
}

export interface Trend {
  direction: 'hausse' | 'baisse' | 'stable'
  /** null quand la valeur ne bouge pas : ni bonne ni mauvaise nouvelle */
  favorable: boolean | null
  /** Pour les lecteurs d'écran : « en hausse, défavorable » */
  label: string
}

/**
 * Sens d'une variation, et si c'est une bonne nouvelle. `bonSens` dit quelle direction est
 * favorable : pour un coût ou une consommation, c'est la baisse.
 */
export function trend(variationPct: number, bonSens: 'hausse' | 'baisse'): Trend {
  if (variationPct === 0) return { direction: 'stable', favorable: null, label: 'stable' }
  const direction = variationPct > 0 ? 'hausse' : 'baisse'
  const favorable = direction === bonSens
  return {
    direction,
    favorable,
    label: `en ${direction}, ${favorable ? 'favorable' : 'défavorable'}`,
  }
}
