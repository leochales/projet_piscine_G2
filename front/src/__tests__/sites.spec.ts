import { describe, expect, it } from 'vitest'

import { DEFAULT_DIRECTION, nextSort, sortSites } from '@/lib/sites'
import type { SiteOverview } from '@/types/energy'

const row = (
  id: string,
  consommationKw: number | null,
  capaciteKw: number,
  statut: 'bonne' | 'partielle' | 'mauvaise' = 'bonne',
): SiteOverview => ({
  site: { id, nom: id, type: 'bureaux', capaciteKw },
  consommationKw,
  picPrevu: null,
  qualite: statut === 'partielle' ? { statut, heuresManquantes: 2 } : { statut },
})

const rows = [
  row('SITE003', null, 1360, 'partielle'),
  row('SITE001', 320, 750),
  row('SITE002', 1640, 1900, 'mauvaise'),
  row('SITE004', 760, 800),
]
const ids = (list: SiteOverview[]) => list.map((r) => r.site.id)
const last = (list: SiteOverview[]) => list[list.length - 1]!.site.id

describe('sortSites', () => {
  it('trie par site, consommation ou part de la capacité', () => {
    expect(ids(sortSites(rows, 'site', 'asc'))).toEqual([
      'SITE001',
      'SITE002',
      'SITE003',
      'SITE004',
    ])
    expect(ids(sortSites(rows, 'consommation', 'desc'))).toEqual([
      'SITE002',
      'SITE004',
      'SITE001',
      'SITE003',
    ])
    // 760/800 = 95 % passe devant 1640/1900 = 86 %, alors qu'il consomme moins
    expect(ids(sortSites(rows, 'capacite', 'desc'))).toEqual([
      'SITE004',
      'SITE002',
      'SITE001',
      'SITE003',
    ])
  })

  it('met toujours en dernier un site sans mesure, dans un sens comme dans l’autre', () => {
    expect(last(sortSites(rows, 'consommation', 'asc'))).toBe('SITE003')
    expect(last(sortSites(rows, 'consommation', 'desc'))).toBe('SITE003')
  })

  it('trie la qualité du pire au meilleur en sens décroissant, puis par site à égalité', () => {
    expect(ids(sortSites(rows, 'qualite', 'desc'))).toEqual([
      'SITE002',
      'SITE003',
      'SITE001',
      'SITE004',
    ])
  })

  it('ne modifie pas la liste reçue', () => {
    const before = ids(rows)
    sortSites(rows, 'consommation', 'desc')
    expect(ids(rows)).toEqual(before)
  })

  it('garde l’ordre entre deux sites sans mesure', () => {
    const both = [row('B', null, 100), row('A', null, 100)]
    expect(ids(sortSites(both, 'consommation', 'asc'))).toEqual(['B', 'A'])
  })
})

describe('nextSort', () => {
  it('trie une nouvelle colonne dans son sens par défaut, puis inverse au 2e clic', () => {
    const first = nextSort({ key: 'site', direction: 'asc' }, 'capacite')
    expect(first).toEqual({ key: 'capacite', direction: DEFAULT_DIRECTION.capacite })
    expect(nextSort(first, 'capacite')).toEqual({ key: 'capacite', direction: 'asc' })
    expect(nextSort({ key: 'site', direction: 'desc' }, 'site').direction).toBe('asc')
    expect(nextSort({ key: 'site', direction: 'asc' }, 'site').direction).toBe('desc')
  })
})
