import { computed } from 'vue'
import { toast } from 'vue-sonner'

import { canAcknowledgeAlerts, canDecideRecommendations } from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'
import { ACTION_ROLES, useUserStore } from '@/stores/user'

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

/** Prendre une alerte en compte, avec le retour à l'utilisateur */
export function useAcknowledgeAlert() {
  const operations = useOperationsStore()

  return async function acknowledge(alertId: string) {
    const alert = operations.alerts.find((a) => a.id === alertId)
    try {
      await operations.acknowledge(alertId)
      toast.success('Alerte prise en compte', {
        description: alert && `${alert.siteId} · ${alert.message}`,
      })
    } catch {
      notifyActionFailed()
    }
  }
}

/**
 * Qui peut prendre une alerte en compte sur un site : un rôle de gestion, et seulement avec les
 * données simulées tant que l'API ne sait pas l'enregistrer (US7)
 */
export function useCanAcknowledge() {
  const user = useUserStore()
  return (siteId: string) => canAcknowledgeAlerts() && user.canActOn(siteId)
}

/**
 * Pourquoi les boutons d'action manquent, à afficher au-dessus des listes (null : rien à
 * dire). Un rôle de consultation ne peut pas agir ; avec les vraies données, personne ne
 * peut agir tant que l'API ne sait pas enregistrer les actions (US7).
 */
export function useActionsNotice() {
  const user = useUserStore()
  return computed(() => {
    if (!user.hasAnyRole(ACTION_ROLES)) {
      return 'Lecture seule : les actions sont réservées aux gestionnaires.'
    }
    if (!canAcknowledgeAlerts() || !canDecideRecommendations()) {
      return 'Prendre une alerte en compte et décider d’une recommandation ne sont pas encore possibles : ces actions arriveront prochainement.'
    }
    return null
  })
}
