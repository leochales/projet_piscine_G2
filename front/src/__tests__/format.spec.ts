import { describe, expect, it } from 'vitest'

import {
  formatAge,
  formatEur,
  formatKw,
  formatPct,
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

  it('exprime une heure par rapport à aujourd’hui', () => {
    const now = new Date(2026, 9, 21, 9)
    expect(formatRelativeHour(new Date(2026, 9, 21, 15).toISOString(), now)).toBe(
      "aujourd'hui 15 h",
    )
    expect(formatRelativeHour(new Date(2026, 9, 22, 14).toISOString(), now)).toBe('demain 14 h')
    expect(formatRelativeHour(new Date(2026, 9, 24, 8).toISOString(), now)).toBe('sam. 24 8 h')
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
})
