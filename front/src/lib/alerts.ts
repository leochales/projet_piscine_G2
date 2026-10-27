import type { Alert, Severity } from '@/types/energy'

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
