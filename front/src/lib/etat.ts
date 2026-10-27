// Transmission et capteurs des sites (GET /api/sites/etat), vers ce qu'affiche le dashboard (US4).

import type { CapteurApi, EtatSiteApi } from '@/types/api'
import type { Sensor, SiteStatus } from '@/types/energy'

const CAPTEURS: Record<CapteurApi, Sensor> = {
  consumption: 'consommation',
  electrical: 'electrique',
  temperature: 'temperature',
  humidity: 'humidite',
  network: 'reseau',
}

export const SENSOR_LABELS: Record<Sensor, string> = {
  consommation: 'compteur de consommation',
  electrique: 'mesures électriques',
  temperature: 'température',
  humidite: 'humidité',
  reseau: 'réseau',
}

/** Minutes reconstituées à partir desquelles une heure est marquée sur la courbe (¼ d'heure) */
export const MINUTES_RECONSTITUEES_MARQUEES = 15

const ETATS: Record<NonNullable<EtatSiteApi['etat_capteurs']>, SiteStatus['etatCapteurs']> = {
  ok: 'ok',
  degraded: 'degrade',
  critical: 'critique',
}

export function toSiteStatus(api: EtatSiteApi): SiteStatus {
  return {
    siteId: api.id_site,
    nomSite: api.nom,
    transmission: api.transmet === null ? 'inconnu' : api.transmet ? 'ok' : 'muet',
    derniereMesureLe: api.derniere_mesure_le,
    capteursEnPanne: api.capteurs_en_panne.map((c) => CAPTEURS[c]),
    etatCapteurs: api.etat_capteurs === null ? null : ETATS[api.etat_capteurs],
    retablissementPrevu: api.retablissement_prevu,
  }
}

/**
 * Ce que dit le bandeau du dashboard. La vue gold.etat_site met `transmet` à null pour tous
 * les sites quand notre collecte est arrêtée : c'est alors elle qu'on signale, pas les sites.
 */
export function transmissionSummary(statuses: readonly SiteStatus[]) {
  return {
    collecteArretee: statuses.length > 0 && statuses.every((s) => s.transmission === 'inconnu'),
    sitesMuets: statuses.filter((s) => s.transmission === 'muet'),
  }
}

/**
 * Rétablissement annoncé, s'il est encore à venir. Un rétablissement passé est celui du dernier
 * état lu des capteurs : l'annoncer comme « prévu » serait faux.
 */
export function upcomingRecovery(status: SiteStatus, now: Date = new Date()): string | null {
  const iso = status.retablissementPrevu
  return iso !== null && new Date(iso).getTime() > now.getTime() ? iso : null
}

/** « réseau, température » : capteurs en panne d'un site */
export function describeSensors(sensors: readonly Sensor[]): string {
  return sensors.map((s) => SENSOR_LABELS[s]).join(', ')
}
