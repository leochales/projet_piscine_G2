import type { Severity, SiteType } from '@/types/energy'

export const SITE_TYPE_LABELS: Record<SiteType, string> = {
  bureaux: 'Bureaux',
  usine: 'Usine',
  data_center: 'Data center',
  hopital: 'Hôpital',
  entrepot: 'Entrepôt',
  laboratoire: 'Laboratoire',
  commerce: 'Commerce',
}

/** Libellé d'un type de site ; un type inconnu est affiché tel que l'API le renvoie */
export function siteTypeLabel(type: string): string {
  return SITE_TYPE_LABELS[type as SiteType] ?? type
}

export const SEVERITY_LABELS: Record<Severity, string> = {
  critique: 'critique',
  moyenne: 'moyenne',
  faible: 'faible',
}
