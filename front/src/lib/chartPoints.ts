// Axe horaire de la courbe d'un site (ConsumptionChart.vue) : mesures, heure en cours,
// prévisions. Gardé hors du composant pour être testé sans dessiner le graphique.

import { junctionIndex } from '@/lib/mesures'
import { hoursBetween, predictedPeak } from '@/lib/predictions'
import type { SiteSeries } from '@/types/energy'

export interface ChartPoint {
  t: string
  mesure: number | null
  kwh: number | null
  cout: number | null
  imputees: number
  pred: number | null
  basse: number | null
  haute: number | null
  pic: number | null // maximum de l'heure prévu
}

export const emptyPoint = (t: string): ChartPoint => ({
  t,
  mesure: null,
  kwh: null,
  cout: null,
  imputees: 0,
  pred: null,
  basse: null,
  haute: null,
  pic: null,
})

/**
 * Un seul axe horaire : les mesures, les heures ni closes ni prévues, puis les prédictions.
 * La dernière heure bien mesurée sert aussi de départ à la prédiction, pour que les courbes
 * se rejoignent sans plonger sur une heure de panne (lib/mesures.ts, junctionIndex).
 */
export function buildChartPoints({ mesures, predictions }: SiteSeries): ChartPoint[] {
  const junctionAt = junctionIndex(mesures)

  // L'heure en cours, ni close ni prévue, reste vide : « maintenant » tombe dans la bonne heure
  const last = mesures[mesures.length - 1]
  const first = predictions[0]
  const empty = last && first ? hoursBetween(last.horodatage, first.horodatage).map(emptyPoint) : []

  return [
    ...mesures.map((m, i) => {
      const junction = i === junctionAt ? m.kw : null
      return {
        ...emptyPoint(m.horodatage),
        mesure: m.kw,
        kwh: m.kwh ?? null,
        cout: m.coutEur ?? null,
        imputees: m.minutesImputees ?? 0,
        pred: junction,
        basse: junction,
        haute: junction,
      }
    }),
    ...empty,
    ...predictions.map((p) => ({
      ...emptyPoint(p.horodatage),
      pred: p.kw,
      basse: p.basseKw,
      haute: p.hauteKw,
      pic: p.picKw,
    })),
  ]
}

/** Dernière heure commencée à `now` : l'heure en cours quand elle est sur l'axe. -1 sinon. */
export function nowIndexOf(points: readonly ChartPoint[], now: number): number {
  let index = -1
  points.forEach((p, i) => {
    if (new Date(p.t).getTime() <= now) index = i
  })
  return index
}

/**
 * Pic prévu, placé sur l'axe : son heure, et sa valeur (maximum de l'heure, sinon moyenne,
 * comme le texte sous le graphique). null sans prévision.
 */
export function peakOnAxis(
  points: readonly ChartPoint[],
  series: SiteSeries,
): { index: number; kw: number } | null {
  const peak = predictedPeak(series.predictions)
  if (!peak) return null
  const index = points.findIndex((p) => p.t === peak.horodatage && p.mesure === null)
  return index === -1 ? null : { index, kw: peak.kw }
}
