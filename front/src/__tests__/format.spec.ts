import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import {
  formatAge,
  formatAxisHour,
  formatClock,
  formatEur,
  formatKw,
  formatPct,
  formatRelativeDateTime,
  formatRelativeHour,
  formatSignedPct,
  formatTonnes,
} from '@/lib/format'

// Intl met des espaces insécables (U+202F, U+00A0) : on les normalise pour comparer
const plain = (s: string) => s.replace(/[  ]/g, ' ')

describe('format', () => {
  it('formate les kW et les euros à la française', () => {
    expect(plain(formatKw(4820))).toBe('4 820 kW')
    expect(plain(formatEur(6140))).toBe('6 140 €')
  })

  it('ajoute le signe aux variations', () => {
    expect(plain(formatSignedPct(4))).toBe('+4 %')
    expect(plain(formatSignedPct(-3))).toBe('−3 %')
  })

  it('formate pourcentages et tonnes, et laisse zéro sans signe', () => {
    expect(plain(formatPct(87))).toBe('87 %')
    expect(plain(formatTonnes(2.14))).toBe('2,1 t')
    expect(plain(formatSignedPct(0))).toBe('0 %')
  })

  it('donne l’âge d’une donnée, arrondi à l’unité affichée', () => {
    const now = new Date('2026-10-23T12:00:00Z')
    const ago = (seconds: number) => new Date(now.getTime() - seconds * 1000)
    expect(formatAge(ago(0), now)).toBe("à l'instant")
    expect(formatAge(ago(9), now)).toBe("à l'instant")
    expect(formatAge(ago(30), now)).toBe('il y a 30 s')
    expect(formatAge(ago(59), now)).toBe('il y a 59 s')
    expect(formatAge(ago(60), now)).toBe('il y a 1 min')
    expect(formatAge(ago(59 * 60 + 59), now)).toBe('il y a 59 min')
    expect(formatAge(ago(2 * 3600), now)).toBe('il y a 2 h')
    // Horloge du poste en retard sur la réponse : jamais de durée négative
    expect(formatAge(ago(-5), now)).toBe("à l'instant")
  })

  it('affiche « — » sans mesure, jamais « 0 kW »', () => {
    expect(formatKw(null)).toBe('—')
    expect(plain(formatKw(0))).toBe('0 kW')
  })
})

// Heures de l'API en UTC, affichées à Paris. Le poste est réglé sur New York pendant ces tests :
// un calcul qui utiliserait encore le fuseau du poste donnerait d'autres heures.
describe('heures en heure de Paris', () => {
  const originalTz = process.env.TZ
  beforeAll(() => (process.env.TZ = 'America/New_York'))
  afterAll(() => (process.env.TZ = originalTz))

  it('exprime une heure par rapport à aujourd’hui, à Paris', () => {
    const now = new Date('2026-10-21T07:00:00Z') // 9 h à Paris
    expect(formatRelativeHour('2026-10-21T13:00:00Z', now)).toBe("aujourd'hui 15 h")
    expect(formatRelativeHour('2026-10-22T12:00:00Z', now)).toBe('demain 14 h')
    expect(formatRelativeHour('2026-10-24T06:00:00Z', now)).toBe('sam. 24 8 h')
  })

  it('change de jour à minuit à Paris, pas à minuit UTC', () => {
    const now = new Date('2026-10-23T21:30:00Z') // 23 h 30 à Paris, même jour en UTC
    expect(formatRelativeHour('2026-10-23T22:30:00Z', now)).toBe('demain 0 h')
    expect(formatRelativeHour('2026-10-23T21:45:00Z', now)).toBe("aujourd'hui 23 h")
  })

  it('suit le passage à l’heure d’hiver (25 octobre 2026, UTC+2 puis UTC+1)', () => {
    expect(formatAxisHour('2026-10-24T22:00:00Z')).toBe('dim. 0 h')
    expect(formatAxisHour('2026-10-25T00:30:00Z')).toBe('dim. 2 h') // 2 h 30, encore UTC+2
    expect(formatAxisHour('2026-10-25T01:30:00Z')).toBe('dim. 2 h') // 2 h 30 une 2e fois, UTC+1
    expect(formatAxisHour('2026-10-25T12:00:00Z')).toBe('dim. 13 h')
  })

  it('suit le passage à l’heure d’été (29 mars 2026, UTC+1 puis UTC+2)', () => {
    expect(formatAxisHour('2026-03-29T00:30:00Z')).toBe('dim. 1 h')
    expect(formatAxisHour('2026-03-29T01:30:00Z')).toBe('dim. 3 h') // 2 h n'existe pas ce jour-là
  })

  it('date une action : aujourd’hui, hier, sinon le jour (heure de Paris)', () => {
    const now = new Date('2026-10-23T08:00:00Z') // 10 h à Paris
    expect(formatRelativeDateTime('2026-10-23T07:05:00Z', now)).toBe("aujourd'hui à 09:05")
    expect(formatRelativeDateTime('2026-10-22T15:40:00Z', now)).toBe('hier à 17:40')
    expect(formatRelativeDateTime('2026-10-20T07:12:00Z', now)).toBe('mar. 20 à 09:12')
    // 23 h 30 UTC le 22 = 1 h 30 le 23 à Paris : c'est aujourd'hui, pas hier
    expect(formatRelativeDateTime('2026-10-22T23:30:00Z', now)).toBe("aujourd'hui à 01:30")
  })

  it('donne l’heure exacte à Paris', () => {
    expect(formatClock(new Date('2026-10-23T12:05:00Z'))).toBe('14:05')
    expect(formatClock(new Date('2026-12-23T12:05:00Z'))).toBe('13:05')
  })
})
