// Conversion des prévisions de l'API (GET /api/sites/{id}/predictions) vers ce qu'affiche
// le dashboard, et choix du pic prévu (US2).

import type { PredictionApi } from '@/types/api'
import type { PredictionPoint } from '@/types/energy'

/**
 * Une heure prévue. Les kWh d'une heure sont la puissance moyenne, en kW, comme pour les
 * mesures (lib/mesures.ts) : la courbe prévue continue la courbe réelle.
 */
export function toPredictionPoint(api: PredictionApi): PredictionPoint {
  // ?? null : une API d'avant ces colonnes (SMARTOPS-95) ne renvoie pas les champs du pic.
  // Absents (undefined), ils passeraient pour des valeurs et donneraient « NaN kW ».
  return {
    horodatage: api.heure,
    kw: api.consommation_kwh,
    basseKw: api.consommation_basse_kwh ?? null,
    hauteKw: api.consommation_haute_kwh ?? null,
    picKw: api.pic_prevu_kw ?? null,
    picBasKw: api.pic_bas_kw ?? null,
    picHautKw: api.pic_haut_kw ?? null,
    picPrevu: api.pic_prevu ?? false,
  }
}

const HOUR_MS = 3_600_000
// Au plus 7 jours d'heures vides (collecte arrêtée longtemps)
const MAX_EMPTY_HOURS = 7 * 24

/**
 * Heures entre la dernière mesure et la première prévision, exclues toutes deux.
 * Les mesures s'arrêtent à la dernière heure close et les prévisions commencent à l'heure
 * pleine suivante : l'heure en cours n'est ni l'une ni l'autre. Le graphique la garde vide,
 * pour que l'axe montre toutes les heures.
 */
export function hoursBetween(lastMeasured: string, firstPredicted: string): string[] {
  const end = new Date(firstPredicted).getTime()
  const hours: string[] = []
  let t = new Date(lastMeasured).getTime() + HOUR_MS
  while (t < end && hours.length < MAX_EMPTY_HOURS) {
    hours.push(new Date(t).toISOString())
    t += HOUR_MS
  }
  return hours
}

export interface PredictedPeak {
  horodatage: string
  kw: number
  basseKw: number | null // null : pas de fourchette
  hauteKw: number | null
  // 'maximum' : maximum de l'heure prévu par le modèle
  // 'moyenne' : le modèle ne le donne pas, on prend la moyenne horaire
  mesure: 'maximum' | 'moyenne'
}

/** Valeur qui sert à repérer le pic d'une heure : son maximum s'il est prévu, sinon sa moyenne */
function peakOfHour(point: PredictionPoint): PredictedPeak {
  if (point.picKw !== null) {
    return {
      horodatage: point.horodatage,
      kw: point.picKw,
      basseKw: point.picBasKw,
      hauteKw: point.picHautKw,
      mesure: 'maximum',
    }
  }
  return {
    horodatage: point.horodatage,
    kw: point.kw,
    basseKw: point.basseKw,
    hauteKw: point.hauteKw,
    mesure: 'moyenne',
  }
}

/**
 * Heure du pic prévu, ou null sans prévision.
 * Une moyenne horaire lisse les pointes de quelques minutes : on compare le maximum de
 * l'heure quand le modèle le donne, comme pour l'alerte de pic prévu.
 */
export function predictedPeak(predictions: readonly PredictionPoint[]): PredictedPeak | null {
  let best: PredictedPeak | null = null
  for (const point of predictions) {
    const peak = peakOfHour(point)
    if (best === null || peak.kw > best.kw) best = peak
  }
  return best
}
