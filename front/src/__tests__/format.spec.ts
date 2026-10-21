import { describe, expect, it } from 'vitest'

import { formatEur, formatKw, formatRelativeHour, formatSignedPct } from '@/lib/format'

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
  })
})
