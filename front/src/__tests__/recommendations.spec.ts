import { describe, expect, it } from 'vitest'

import {
  ACCEPTEE_EN_COURS_JOURS,
  currentRecommendations,
  decidedThisMonth,
  isStaleAccepted,
  listedRecommendations,
  toRecommendation,
} from '@/lib/recommendations'
import { recommandations } from '@/mocks/recommandations'
import type { RecommandationApi } from '@/types/api'
import type { Recommendation } from '@/types/energy'

const api: RecommandationApi = {
  id_recommandation: 7,
  id_site: 'SITE002',
  nom_site: 'Usine de Lyon',
  id_alerte: 12,
  regle: 'pic_prevu',
  titre: 'Décaler la ligne 2 après 20 h',
  description: 'Pic prévu à 14 h',
  date_creation: '2026-10-26T13:15:00Z',
  gain_estime_eur: 380,
  periode_gain: 'unique',
  statut: 'acceptee',
  decide_par: '8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10',
  decide_le: '2026-10-26T13:30:00Z',
}

describe('toRecommendation', () => {
  it('convertit la réponse de GET /api/recommandations', () => {
    expect(toRecommendation(api)).toEqual({
      id: '7',
      siteId: 'SITE002',
      nomSite: 'Usine de Lyon',
      titre: 'Décaler la ligne 2 après 20 h',
      description: 'Pic prévu à 14 h',
      alerteId: '12',
      gainEstimeEur: 380,
      periodeGain: 'unique',
      statut: 'acceptee',
      creeeLe: '2026-10-26T13:15:00Z',
      decideeLe: '2026-10-26T13:30:00Z',
    })
  })

  it('garde les champs absents à null (sans alerte, gain non estimé)', () => {
    const rec = toRecommendation({
      ...api,
      id_alerte: null,
      gain_estime_eur: null,
      periode_gain: null,
    })
    expect(rec).toMatchObject({ alerteId: null, gainEstimeEur: null, periodeGain: null })
  })

  it('accepte toutes les recommandations simulées (même format que l’API)', () => {
    expect(recommandations.map(toRecommendation)).toHaveLength(recommandations.length)
  })
})

describe('currentRecommendations', () => {
  const rec = (id: string, over: Partial<Recommendation>): Recommendation => ({
    ...toRecommendation(api),
    id,
    statut: 'proposee',
    ...over,
  })

  it('garde les recommandations du site, sans les refusées', () => {
    const liste = [
      rec('A', {}),
      rec('B', { statut: 'refusee' }),
      rec('C', { siteId: 'SITE006' }),
      rec('D', { statut: 'acceptee' }),
    ]
    expect(currentRecommendations(liste, 'SITE002').map((r) => r.id)).toEqual(['A', 'D'])
  })

  it('met les recommandations à décider en premier, puis les plus récentes', () => {
    const liste = [
      rec('acceptee-recente', { statut: 'acceptee', creeeLe: '2026-10-26T12:00:00Z' }),
      rec('proposee-ancienne', { creeeLe: '2026-10-20T08:00:00Z' }),
      rec('proposee-recente', { creeeLe: '2026-10-26T08:00:00Z' }),
    ]
    expect(currentRecommendations(liste, 'SITE002').map((r) => r.id)).toEqual([
      'proposee-recente',
      'proposee-ancienne',
      'acceptee-recente',
    ])
  })

  it('compare les dates, quel que soit leur format (décalage horaire, précision)', () => {
    // 13:45+01:00 = 12:45 UTC : plus ancienne que 13:15 UTC, alors qu'en texte
    // « 13:45 » passerait devant « 13:15 »
    const liste = [
      rec('decalage', { creeeLe: '2026-10-26T13:45:00+01:00' }),
      rec('utc', { creeeLe: '2026-10-26T13:15:00.000Z' }),
    ]
    expect(currentRecommendations(liste, 'SITE002').map((r) => r.id)).toEqual(['utc', 'decalage'])
  })

  it('ne modifie pas la liste reçue', () => {
    const liste = [rec('B', { creeeLe: '2026-10-20T08:00:00Z' }), rec('A', {})]
    currentRecommendations(liste, 'SITE002')
    expect(liste.map((r) => r.id)).toEqual(['B', 'A'])
  })
})

describe('acceptées en cours, ordre commun et économies du mois', () => {
  const now = new Date('2026-10-26T12:00:00Z')
  const joursAvant = (jours: number) =>
    new Date(now.getTime() - jours * 24 * 3600 * 1000).toISOString()
  const rec = (id: string, over: Partial<Recommendation>): Recommendation => ({
    ...toRecommendation(api),
    id,
    statut: 'proposee',
    decideeLe: null,
    ...over,
  })

  it('une acceptée reste en cours ACCEPTEE_EN_COURS_JOURS jours, puis disparaît des listes', () => {
    const recente = rec('recente', { statut: 'acceptee', decideeLe: joursAvant(2) })
    const ancienne = rec('ancienne', {
      statut: 'acceptee',
      decideeLe: joursAvant(ACCEPTEE_EN_COURS_JOURS + 1),
    })

    expect(isStaleAccepted(recente, now)).toBe(false)
    expect(isStaleAccepted(ancienne, now)).toBe(true)
    expect(currentRecommendations([recente, ancienne], 'SITE002', now).map((r) => r.id)).toEqual([
      'recente',
    ])
    expect(listedRecommendations([recente, ancienne], now).map((r) => r.id)).toEqual(['recente'])
  })

  it('l’écran 3 et la page du site trient de la même façon', () => {
    const liste = [
      rec('acceptee', { statut: 'acceptee', decideeLe: joursAvant(1), creeeLe: joursAvant(1) }),
      rec('proposee-ancienne', { creeeLe: joursAvant(5) }),
      rec('proposee-recente', { creeeLe: joursAvant(0) }),
    ]
    const ordre = ['proposee-recente', 'proposee-ancienne', 'acceptee']

    expect(listedRecommendations(liste, now).map((r) => r.id)).toEqual(ordre)
    expect(currentRecommendations(liste, 'SITE002', now).map((r) => r.id)).toEqual(ordre)
  })

  it('compte une décision dans le mois où elle a été prise', () => {
    expect(decidedThisMonth(rec('a', { decideeLe: '2026-10-03T10:00:00Z' }), now)).toBe(true)
    expect(decidedThisMonth(rec('b', { decideeLe: '2026-09-20T10:00:00Z' }), now)).toBe(false)
    expect(decidedThisMonth(rec('c', { decideeLe: null }), now)).toBe(false)
  })
})
