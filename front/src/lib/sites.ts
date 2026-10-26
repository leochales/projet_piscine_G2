import { capacityPct } from '@/lib/indicators'
import type { DataQuality, SiteOverview } from '@/types/energy'

export type SiteSortKey = 'site' | 'consommation' | 'capacite' | 'qualite'
export type SortDirection = 'asc' | 'desc'

export const SITE_SORT_LABELS: Record<SiteSortKey, string> = {
  site: 'Site',
  consommation: 'Consommation',
  capacite: '% de la capacité',
  qualite: 'Qualité des données',
}

// Premier clic sur une colonne : le plus utile en premier (le site le plus chargé, les données
// les moins fiables) ; le nom du site, lui, dans l'ordre alphabétique
export const DEFAULT_DIRECTION: Record<SiteSortKey, SortDirection> = {
  site: 'asc',
  consommation: 'desc',
  capacite: 'desc',
  qualite: 'desc',
}

export interface SiteSort {
  key: SiteSortKey
  direction: SortDirection
}

/** Clic sur une colonne : inverse le sens si elle est déjà triée, sinon son sens par défaut */
export function nextSort(current: SiteSort, key: SiteSortKey): SiteSort {
  if (current.key === key) {
    return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
  }
  return { key, direction: DEFAULT_DIRECTION[key] }
}

// Du meilleur au pire : un tri décroissant met les données les moins fiables en tête
const QUALITY_RANK: Record<DataQuality['statut'], number> = { bonne: 0, partielle: 1, mauvaise: 2 }

function value(row: SiteOverview, key: SiteSortKey): number | string | null {
  switch (key) {
    case 'site':
      return row.site.id
    case 'consommation':
      return row.consommationKw
    case 'capacite':
      return capacityPct(row.consommationKw, row.site.capaciteKw)
    case 'qualite':
      return QUALITY_RANK[row.qualite.statut]
  }
}

/**
 * Sites triés, sans modifier la liste reçue. Un site sans mesure va toujours en fin de liste,
 * dans un sens comme dans l'autre : « — » n'est ni le plus petit ni le plus grand.
 */
export function sortSites(
  rows: readonly SiteOverview[],
  key: SiteSortKey,
  direction: SortDirection,
): SiteOverview[] {
  const sign = direction === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = value(a, key)
    const vb = value(b, key)
    if (va === null || vb === null) return va === vb ? 0 : va === null ? 1 : -1
    if (va < vb) return -sign
    if (va > vb) return sign
    return a.site.id.localeCompare(b.site.id) // ordre stable à valeur égale
  })
}
