import type { RecommandationApi } from '@/types/api'
import type { Recommendation } from '@/types/energy'

/** Réponse de GET /api/recommandations → recommandation affichée par le dashboard */
export function toRecommendation(api: RecommandationApi): Recommendation {
  return {
    id: String(api.id_recommandation),
    siteId: api.id_site,
    nomSite: api.nom_site,
    titre: api.titre,
    description: api.description,
    alerteId: api.id_alerte === null ? null : String(api.id_alerte),
    gainEstimeEur: api.gain_estime_eur,
    periodeGain: api.periode_gain,
    statut: api.statut,
    creeeLe: api.date_creation,
    decideeLe: api.decide_le,
  }
}

/** Durée pendant laquelle une recommandation acceptée reste « en cours d'application » */
export const ACCEPTEE_EN_COURS_JOURS = 30

const JOUR_MS = 24 * 3600 * 1000

// Dates comparées en valeur, pas en texte : l'API peut renvoyer un décalage horaire
// (+01:00) ou une autre précision que les données simulées
const time = (iso: string) => Date.parse(iso)

/** Acceptée il y a plus de ACCEPTEE_EN_COURS_JOURS : elle n'est plus « en cours » */
export function isStaleAccepted(rec: Recommendation, now: Date = new Date()): boolean {
  if (rec.statut !== 'acceptee' || rec.decideeLe === null) return false
  return now.getTime() - time(rec.decideeLe) > ACCEPTEE_EN_COURS_JOURS * JOUR_MS
}

/**
 * Ordre commun à l'écran 3 et à la page d'un site : celles qui restent à décider d'abord,
 * puis les autres ; les plus récentes en premier. Ne modifie pas la liste reçue.
 */
export function sortRecommendations(recommendations: Recommendation[]): Recommendation[] {
  const rang = (r: Recommendation) => (r.statut === 'proposee' ? 0 : 1)
  return [...recommendations].sort((a, b) => rang(a) - rang(b) || time(b.creeeLe) - time(a.creeeLe))
}

/**
 * Recommandations de l'écran 3 : toutes, sauf les acceptées depuis plus de
 * ACCEPTEE_EN_COURS_JOURS. Une recommandation refusée pendant la session reste visible avec
 * son badge (les refusées ne sont pas rechargées).
 */
export function listedRecommendations(
  recommendations: Recommendation[],
  now: Date = new Date(),
): Recommendation[] {
  return sortRecommendations(recommendations.filter((r) => !isStaleAccepted(r, now)))
}

/**
 * Recommandations en cours d'un site : celles qui restent à décider, puis celles acceptées
 * récemment (en cours d'application). Les refusées sont écartées.
 */
export function currentRecommendations(
  recommendations: Recommendation[],
  siteId: string,
  now: Date = new Date(),
): Recommendation[] {
  return listedRecommendations(
    recommendations.filter((r) => r.siteId === siteId && r.statut !== 'refusee'),
    now,
  )
}

/** Décidée pendant le mois en cours (heure locale) : comptée dans les économies du mois */
export function decidedThisMonth(rec: Recommendation, now: Date = new Date()): boolean {
  if (rec.decideeLe === null) return false
  const decision = new Date(rec.decideeLe)
  return decision.getFullYear() === now.getFullYear() && decision.getMonth() === now.getMonth()
}
