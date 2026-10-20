import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

// Rôles du wireframe. Ils viendront du token Keycloak (ticket dédié).
export type Role = 'energy_manager' | 'site_manager' | 'direction'

const ROLE_LABELS: Record<Role, string> = {
  energy_manager: 'Responsable énergie',
  site_manager: 'Responsable de site',
  direction: 'Direction',
}

export const useUserStore = defineStore('user', () => {
  const role = ref<Role>('energy_manager')
  const roleLabel = computed(() => ROLE_LABELS[role.value])

  return { role, roleLabel }
})
