// Conversion des mesures de l'API (GET /api/sites/…) vers ce qu'affiche le dashboard.
// Le tarif (0,14 €/kWh) est déjà appliqué par l'API : cout_eur est repris tel quel.

import { TIME_ZONE } from '@/lib/format'
import type { ConsommationHoraireApi, DerniereMesureApi } from '@/types/api'
import type {
  ConsumptionPoint,
  DataQuality,
  FleetKpis,
  FleetTrend,
  SiteOverview,
  SiteType,
} from '@/types/energy'

// Types renvoyés par l'API Mock / app.site, vers les libellés du dashboard
const SITE_TYPES: Record<string, SiteType> = {
  office: 'bureaux',
  bureaux: 'bureaux',
  factory: 'usine',
  usine: 'usine',
  datacenter: 'data_center',
  data_center: 'data_center',
  hospital: 'hopital',
  hopital: 'hopital',
  retail: 'commerce',
  warehouse: 'entrepot',
  entrepot: 'entrepot',
  laboratory: 'laboratoire',
  laboratoire: 'laboratoire',
}

// Même facteur que les données simulées (mocks/data.ts) : l'API ne fournit pas le CO₂
const FACTEUR_CO2_KG_KWH = 0.052

const QUALITES: Record<DerniereMesureApi['data_quality'], DataQuality> = {
  good: { statut: 'bonne' },
  partial: { statut: 'partielle' },
  degraded: { statut: 'mauvaise' },
  critical: { statut: 'mauvaise' },
}

export function toSiteOverview(api: DerniereMesureApi): SiteOverview {
  return {
    site: {
      id: api.id_site,
      nom: api.nom,
      type: SITE_TYPES[api.type] ?? api.type,
      capaciteKw: api.capacite_kw,
    },
    consommationKw: api.consommation_kw,
    mesureLe: api.horodatage,
    // Le pic prévu vient des prévisions (US2), pas de la dernière mesure
    picPrevu: null,
    qualite: QUALITES[api.data_quality],
  }
}

/**
 * Heure présente : kWh et coût. Les kWh d'une heure sont la puissance moyenne, en kW.
 * Une heure sans mesure est gardée (kw null) : la courbe s'interrompt à cet endroit.
 */
export function toConsumptionPoint(api: ConsommationHoraireApi): ConsumptionPoint {
  return {
    horodatage: api.heure,
    kw: api.consommation_kwh,
    kwh: api.consommation_kwh,
    coutEur: api.cout_eur,
  }
}

export function costsFrom(rows: readonly ConsommationHoraireApi[]) {
  let kwh = 0
  let coutEur = 0
  for (const row of rows) {
    if (row.consommation_kwh !== null) kwh += row.consommation_kwh
    if (row.cout_eur !== null) coutEur += row.cout_eur
  }
  return { coutEur, co2Tonnes: (kwh * FACTEUR_CO2_KG_KWH) / 1000 }
}

const dayParts = new Intl.DateTimeFormat('en-US', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})
const clockParts = new Intl.DateTimeFormat('en-US', {
  timeZone: TIME_ZONE,
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

/** Décalage de Paris à cet instant (ms à ajouter à UTC pour obtenir l'heure locale) */
function offsetMs(date: Date): number {
  const parts = Object.fromEntries(clockParts.formatToParts(date).map((p) => [p.type, p.value]))
  const asUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  )
  return asUtc - date.getTime()
}

/**
 * Minuit à Paris, décalé de `dayOffset` jours calendaires (0 : aujourd'hui, −1 : hier).
 * Le décalage est celui de minuit, pas celui de midi : le jour du changement d'heure,
 * midi est déjà à l'heure d'été (ou d'hiver) alors que minuit ne l'est pas encore.
 */
export function parisMidnight(dayOffset: number, now: Date = new Date()): Date {
  const parts = Object.fromEntries(dayParts.formatToParts(now).map((p) => [p.type, p.value]))
  const shifted = new Date(
    Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day) + dayOffset),
  )
  const localMidnight = Date.UTC(
    shifted.getUTCFullYear(),
    shifted.getUTCMonth(),
    shifted.getUTCDate(),
  )
  let utc = localMidnight
  for (let i = 0; i < 3; i++) {
    const next = localMidnight - offsetMs(new Date(utc))
    if (next === utc) break
    utc = next
  }
  return new Date(utc)
}

function sumCost(rows: readonly ConsommationHoraireApi[], from: number, to: number) {
  return rows.reduce((total, row) => {
    const time = new Date(row.heure).getTime()
    if (row.cout_eur === null || time < from || time >= to) return total
    return total + row.cout_eur
  }, 0)
}

function sumKwh(rows: readonly ConsommationHoraireApi[], from: number, to: number) {
  return rows.reduce((total, row) => {
    const time = new Date(row.heure).getTime()
    if (row.consommation_kwh === null || time < from || time >= to) return total
    return total + row.consommation_kwh
  }, 0)
}

/**
 * Indicateurs du parc à partir des dernières mesures et des heures depuis hier minuit.
 * « vs hier » compare les mêmes heures closes. L'API s'arrête au début de l'heure UTC
 * en cours (`heure < fin`) : cette heure, encore ouverte, n'est comptée ni aujourd'hui ni hier.
 */
export function kpisFrom(
  sites: readonly SiteOverview[],
  heures: readonly ConsommationHoraireApi[],
  now: Date = new Date(),
): FleetKpis {
  const measured = sites.filter((s) => s.consommationKw !== null)
  const todayStart = parisMidnight(0, now).getTime()
  const yesterdayStart = parisMidnight(-1, now).getTime()
  const fin = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours())
  const elapsed = fin - todayStart
  const todayCost = sumCost(heures, todayStart, fin)
  const yesterdayCost = sumCost(heures, yesterdayStart, yesterdayStart + elapsed)
  return {
    consommationKw: measured.reduce((total, s) => total + s.consommationKw!, 0),
    nbSites: sites.length,
    nbSitesSansMesure: sites.length - measured.length,
    coutJourEur: todayCost,
    variationCoutPct: yesterdayCost === 0 ? 0 : ((todayCost - yesterdayCost) / yesterdayCost) * 100,
    co2JourTonnes: (sumKwh(heures, todayStart, fin) * FACTEUR_CO2_KG_KWH) / 1000,
  }
}

/** Mini-courbes : puissance moyenne heure par heure sur 24 h, coût de chacun des 7 jours */
export function fleetFrom(
  heures: readonly ConsommationHoraireApi[],
  now: Date = new Date(),
): FleetTrend {
  const since = now.getTime() - 24 * 3600 * 1000
  const byHour = new Map<string, number>()
  for (const row of heures) {
    if (row.consommation_kwh === null || new Date(row.heure).getTime() < since) continue
    byHour.set(row.heure, (byHour.get(row.heure) ?? 0) + row.consommation_kwh)
  }
  const consommationKw24h = [...byHour.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, kw]) => kw)

  const coutEurJours7 = Array.from({ length: 7 }, (_, index) => {
    const day = index - 6
    return sumCost(heures, parisMidnight(day, now).getTime(), parisMidnight(day + 1, now).getTime())
  })
  return { consommationKw24h, coutEurJours7 }
}
