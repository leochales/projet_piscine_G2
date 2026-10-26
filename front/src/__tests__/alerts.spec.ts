import { describe, expect, it } from 'vitest'

import { alertSites, filterAlerts, NO_FILTER } from '@/lib/alerts'
import type { Alert } from '@/types/energy'

const alert = (id: string, siteId: string, gravite: Alert['gravite']): Alert => ({
  id,
  siteId,
  nomSite: siteId,
  type: 'anomaly',
  gravite,
  message: id,
  debut: '2026-10-26T10:00:00Z',
  valeurKw: null,
  seuilKw: null,
  priseEnCompte: false,
})

const alerts = [
  alert('A1', 'SITE002', 'critique'),
  alert('A2', 'SITE003', 'moyenne'),
  alert('A3', 'SITE002', 'faible'),
  alert('A4', 'SITE004', 'moyenne'),
]
const ids = (list: Alert[]) => list.map((a) => a.id)

describe('filterAlerts', () => {
  it('sans filtre, garde toutes les alertes', () => {
    expect(ids(filterAlerts(alerts, NO_FILTER))).toEqual(['A1', 'A2', 'A3', 'A4'])
  })

  it('filtre par gravité, par site, ou les deux', () => {
    expect(ids(filterAlerts(alerts, { gravite: 'moyenne', siteId: 'tous' }))).toEqual(['A2', 'A4'])
    expect(ids(filterAlerts(alerts, { gravite: 'toutes', siteId: 'SITE002' }))).toEqual([
      'A1',
      'A3',
    ])
    expect(ids(filterAlerts(alerts, { gravite: 'critique', siteId: 'SITE002' }))).toEqual(['A1'])
    expect(filterAlerts(alerts, { gravite: 'critique', siteId: 'SITE004' })).toEqual([])
  })
})

describe('alertSites', () => {
  it('liste une fois chaque site ayant une alerte, dans l’ordre', () => {
    expect(alertSites(alerts)).toEqual(['SITE002', 'SITE003', 'SITE004'])
  })
})
