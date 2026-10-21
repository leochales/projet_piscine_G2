import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

// Rôles du wireframe. Ils viendront du token Keycloak (ticket dédié),
// et les sites suivis de la table app.utilisateur_site.
export type Role = 'energy_manager' | 'site_manager' | 'direction'

export const ROLE_LABELS: Record<Role, string> = {
  energy_manager: 'Responsable énergie',
  site_manager: 'Responsable de site',
  direction: 'Direction',
}

export const useUserStore = defineStore('user', () => {
  const role = ref<Role>('energy_manager')
  // Sites dont l'utilisateur est responsable (utilisé pour le rôle site_manager)
  const siteIds = ref<string[]>(['SITE002'])

  const roleLabel = computed(() => ROLE_LABELS[role.value])

  /**
   * Règle du wireframe (écran 3) : le responsable énergie agit sur tous les sites,
   * le responsable de site seulement sur les siens, la direction est en lecture seule.
   */
  function canActOn(siteId: string) {
    if (role.value === 'energy_manager') return true
    if (role.value === 'site_manager') return siteIds.value.includes(siteId)
    return false
  }

  return { role, siteIds, roleLabel, canActOn }
})
