import { computed } from 'vue'
import { toast } from 'vue-sonner'

import { ApiError } from '@/lib/api'
import { useOperationsStore } from '@/stores/operations'
import { ACTION_ROLES, useUserStore } from '@/stores/user'

// Retour après chaque action de l'écran 3 et de la page d'un site : confirmation discrète,
// ou erreur à réessayer. Rien n'est affiché comme fait tant que le service ne l'a pas
// confirmé (store).

export const notifyActionFailed = () =>
  toast.error('Action impossible', {
    description: 'Le service de données ne répond pas. Réessayez dans un instant.',
  })

const isStatus = (error: unknown, status: number) =>
  error instanceof ApiError && error.status === status

/** Action refusée par l'API sur ce site (403, 404), ou service en panne */
function notifyRefusedOrFailed(error: unknown) {
  if (isStatus(error, 403) || isStatus(error, 404)) {
    toast.error('Action impossible', {
      description: 'Vous ne pouvez pas agir sur ce site.',
    })
  } else {
    notifyActionFailed()
  }
}

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
    } catch (error) {
      if (isStatus(error, 409)) {
        // Décidée entre-temps par quelqu'un d'autre : la liste montre sa décision
        toast.info('Recommandation déjà décidée', {
          description: 'Quelqu’un l’a acceptée ou refusée avant vous.',
        })
        await operations.reloadRecommendations().catch(() => {})
      } else {
        notifyRefusedOrFailed(error)
      }
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
    } catch (error) {
      if (isStatus(error, 409)) {
        // Prise en compte par quelqu'un d'autre, ou terminée entre-temps
        toast.info('Alerte déjà traitée', {
          description: 'Elle a été prise en compte par quelqu’un d’autre, ou vient de se terminer.',
        })
        await operations.reloadAlerts().catch(() => {})
      } else {
        notifyRefusedOrFailed(error)
      }
    }
  }
}

/** Qui peut prendre une alerte en compte sur un site : mêmes règles que l'API (US7) */
export function useCanAcknowledge() {
  const user = useUserStore()
  return (siteId: string) => user.canActOn(siteId)
}

/**
 * Pourquoi les boutons d'action manquent, à afficher au-dessus des listes (null : rien à
 * dire) : un rôle de consultation ne peut pas agir.
 */
export function useActionsNotice() {
  const user = useUserStore()
  return computed(() =>
    user.hasAnyRole(ACTION_ROLES)
      ? null
      : 'Lecture seule : les actions sont réservées aux gestionnaires.',
  )
}
