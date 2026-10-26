import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { KeycloakTokenParsed } from 'keycloak-js'

// Rôles du realm Keycloak enervision, du plus large au plus restreint
export const ROLE_LABELS = {
  'GESTION-CLIENT': 'Gestion client',
  'GESTION-SITE': 'Gestion site',
  'CONSULT-CLIENT': 'Consultation client',
  'CONSULT-SITE': 'Consultation site',
  MONITORING: 'Monitoring',
} as const

export type Role = keyof typeof ROLE_LABELS

const ROLES = Object.keys(ROLE_LABELS) as Role[]

/** Rôles qui donnent accès aux écrans du dashboard */
export const DASHBOARD_ROLES: readonly Role[] = [
  'GESTION-CLIENT',
  'GESTION-SITE',
  'CONSULT-CLIENT',
  'CONSULT-SITE',
]

/** Rôles qui peuvent agir sur les alertes et les recommandations (écran 3) */
export const ACTION_ROLES: readonly Role[] = ['GESTION-CLIENT', 'GESTION-SITE']

const isRole = (value: string): value is Role => ROLES.includes(value as Role)

export const useUserStore = defineStore('user', () => {
  const roles = ref<Role[]>([])
  const nom = ref('')
  const email = ref('')

  /** Libellé du rôle le plus large de l'utilisateur */
  const roleLabel = computed(() => {
    const main = ROLES.find((role) => roles.value.includes(role))
    return main ? ROLE_LABELS[main] : 'Aucun rôle'
  })

  function setFromToken(claims: KeycloakTokenParsed) {
    roles.value = (claims.realm_access?.roles ?? []).filter(isRole)
    email.value = claims.email ?? ''
    const fullName = [claims.given_name, claims.family_name].filter(Boolean).join(' ')
    nom.value = claims.name || fullName || email.value
  }

  function hasAnyRole(allowed: readonly Role[]) {
    return allowed.some((role) => roles.value.includes(role))
  }

  /**
   * Un utilisateur voit tous les sites de son client : seuls les rôles de gestion agissent
   * sur les alertes et les recommandations, les rôles de consultation sont en lecture seule.
   */
  function canActOn(_siteId: string) {
    return hasAnyRole(ACTION_ROLES)
  }

  return { roles, nom, email, roleLabel, setFromToken, hasAnyRole, canActOn }
})
