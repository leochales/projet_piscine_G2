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

export const SEVERITY_LABELS: Record<Severity, string> = {
  critique: 'critique',
  moyenne: 'moyenne',
  faible: 'faible',
}
