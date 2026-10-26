import { toast } from 'vue-sonner'

import { useOperationsStore } from '@/stores/operations'

// Retour après chaque action de l'écran 3 et de la page d'un site : confirmation discrète,
// ou erreur à réessayer. Rien n'est affiché comme fait tant que le service ne l'a pas
// confirmé (store).

export const notifyActionFailed = () =>
  toast.error('Action impossible', {
    description: 'Le service de données ne répond pas. Réessayez dans un instant.',
  })

/** Accepter ou refuser une recommandation, avec le retour à l'utilisateur */
export function useDecideRecommendation() {
  const operations = useOperationsStore()

  return async function decide(id: string, statut: 'acceptee' | 'refusee') {
    const rec = operations.recommendations.find((r) => r.id === id)
    try {
      await operations.decide(id, statut)
      toast.success(statut === 'acceptee' ? 'Recommandation acceptée' : 'Recommandation refusée', {
        description: rec && `${rec.siteId} · ${rec.titre}`,
      })
    } catch {
      notifyActionFailed()
    }
  }
}
