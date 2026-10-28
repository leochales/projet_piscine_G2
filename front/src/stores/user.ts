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
  // Compte connu de Keycloak mais pas de l'API (absent de app.utilisateur) : aucune
  // entreprise, donc aucune donnée. Seule la page « compte non rattaché » s'affiche.
  const unlinked = ref(false)
  // Sites attribués (GET /api/moi), pour un rôle *-SITE. null : l'API n'a pas encore
  // répondu (main.ts relance l'appel) ; [] : aucun site attribué
  const sites = ref<string[] | null>(null)

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
   * Mêmes règles que l'API (US7) : GESTION-CLIENT agit sur tous les sites de son client,
   * GESTION-SITE sur ses sites attribués. Les rôles de consultation sont en lecture seule.
   */
  function canActOn(siteId: string) {
    if (roles.value.includes('GESTION-CLIENT')) return true
    return roles.value.includes('GESTION-SITE') && (sites.value?.includes(siteId) ?? false)
  }

  return { roles, nom, email, unlinked, sites, roleLabel, setFromToken, hasAnyRole, canActOn }
})
