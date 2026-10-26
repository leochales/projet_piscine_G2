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
  }
}

/**
 * Recommandations en cours d'un site : celles qui restent à décider, puis celles acceptées
 * (en cours d'application). Les refusées sont écartées. Les plus récentes d'abord.
 */
export function currentRecommendations(
  recommendations: Recommendation[],
  siteId: string,
): Recommendation[] {
  const rang = (r: Recommendation) => (r.statut === 'proposee' ? 0 : 1)
  // Comparées en dates, pas en texte : l'API peut renvoyer un décalage horaire (+01:00)
  // ou une autre précision que les données simulées
  const date = (r: Recommendation) => Date.parse(r.creeeLe)
  return recommendations
    .filter((r) => r.siteId === siteId && r.statut !== 'refusee')
    .sort((a, b) => rang(a) - rang(b) || date(b) - date(a))
}
