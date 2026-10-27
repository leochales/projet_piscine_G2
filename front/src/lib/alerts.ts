import { formatKw, formatRelativeDateTime } from '@/lib/format'
import type { AlerteApi } from '@/types/api'
import type { Alert, AlertType, Severity } from '@/types/energy'

// L'API a 4 niveaux, le dashboard 3. SMARTOPS-26 : un pic à 90 % est « high »,
// « critical » seulement à partir de 110 %. « high » n'est donc pas une alerte critique.
const GRAVITES: Record<AlerteApi['severite'], Severity> = {
  critical: 'critique',
  high: 'moyenne',
  medium: 'moyenne',
  low: 'faible',
}

// Libellé quand l'alerte n'a pas de message (alertes produites par l'ETL ou le modèle)
const TYPE_LABELS: Record<AlertType, string> = {
  threshold: 'Dépassement du seuil de consommation',
  spike: 'Pic de consommation',
  predicted_peak: 'Pic de consommation prévu',
  anomaly: 'Consommation inhabituelle',
  outage: 'Site sans mesure',
  sensor: 'Capteur en panne',
}

/** Réponse de GET /api/alertes → alerte affichée par le dashboard */
export function toAlert(api: AlerteApi): Alert {
  return {
    id: String(api.id_alerte),
    siteId: api.id_site,
    nomSite: api.nom_site,
    type: api.type,
    gravite: GRAVITES[api.severite],
    message: api.message ?? TYPE_LABELS[api.type],
    debut: api.debut,
    valeurKw: api.valeur,
    seuilKw: api.seuil,
    priseEnCompte: api.prise_en_compte,
    // L'API ne donne que l'identifiant Keycloak de la personne : pas de nom à afficher
    priseLe: api.prise_le ?? undefined,
  }
}

/**
 * Mesure comparée au seuil, pour un dépassement (US3) : « 752 kW pour un seuil de 720 kW
 * (+4 %) ». L'écart n'est donné que si le seuil est bien dépassé : une valeur sous le seuil
 * (mesure retombée, ou donnée de l'ETL) n'affiche pas un « −3 % » contradictoire.
 * null si l'alerte n'a pas de mesure ou de seuil.
 */
export function thresholdText(alert: Alert): string | null {
  const { valeurKw, seuilKw } = alert
  if (valeurKw === null || seuilKw === null || seuilKw <= 0) return null
  const text = `${formatKw(valeurKw)} pour un seuil de ${formatKw(seuilKw)}`
  if (valeurKw <= seuilKw) return text
  return `${text} (${formatEcartPct(((valeurKw - seuilKw) / seuilKw) * 100)})`
}

/** Écart au-dessus du seuil. Sous 1 %, un arrondi entier donnerait « +0 % ». */
function formatEcartPct(pct: number): string {
  if (pct < 0.05) return '< 0,1 %'
  if (pct < 1) {
    const dixieme = new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(pct)
    return `+${dixieme} %`
  }
  return `+${Math.round(pct)} %`
}

// Alertes datées par la mesure elle-même : l'heure affichée est celle du dépassement
const MEASURED_TYPES: readonly AlertType[] = ['threshold', 'spike']

/**
 * Heure affichée sous l'alerte : celle de la mesure pour un dépassement ou un pic mesuré,
 * sinon celle du signalement (« signalée … ») : pour un pic prévu, elle ne doit pas être
 * prise pour l'heure du pic.
 */
export function alertTimeLabel(alert: Alert, now: Date = new Date()): string {
  const when = formatRelativeDateTime(alert.debut, now)
  return MEASURED_TYPES.includes(alert.type) ? when : `signalée ${when}`
}

export interface AlertFilter {
  gravite: Severity | 'toutes'
  siteId: string | 'tous'
}

export const NO_FILTER: AlertFilter = { gravite: 'toutes', siteId: 'tous' }

export function filterAlerts(alerts: readonly Alert[], filter: AlertFilter): Alert[] {
  return alerts.filter(
    (a) =>
      (filter.gravite === 'toutes' || a.gravite === filter.gravite) &&
      (filter.siteId === 'tous' || a.siteId === filter.siteId),
  )
}

/** Sites qui ont au moins une alerte, triés : les choix du filtre par site */
export const alertSites = (alerts: readonly Alert[]) =>
  [...new Set(alerts.map((a) => a.siteId))].sort()
