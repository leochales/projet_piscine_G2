import { createRouter, createWebHistory, type LocationQuery } from 'vue-router'

import { DASHBOARD_ROLES, type Role, useUserStore } from '@/stores/user'

const ROLES_CLIENT: readonly Role[] = ['CONSULT-CLIENT', 'GESTION-CLIENT']
const ROLES_SITE: readonly Role[] = ['CONSULT-SITE', 'GESTION-SITE']

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: () => import('@/views/OverviewView.vue'),
      meta: { title: "Vue d'ensemble", roles: DASHBOARD_ROLES },
    },
    {
      path: '/sites/:siteId?',
      name: 'sites',
      component: () => import('@/views/SiteDetailView.vue'),
      props: true,
      meta: { title: 'Sites', roles: DASHBOARD_ROLES },
    },
    {
      path: '/alertes',
      name: 'alerts',
      component: () => import('@/views/AlertsView.vue'),
      meta: { title: 'Alertes et recommandations', roles: DASHBOARD_ROLES },
    },
    {
      path: '/compte-non-rattache',
      name: 'unlinked-account',
      component: () => import('@/views/UnlinkedAccountView.vue'),
      meta: { title: 'Compte non rattaché' },
    },
    {
      path: '/acces-refuse',
      name: 'access-denied',
      component: () => import('@/views/AccessDeniedView.vue'),
      meta: { title: 'Accès refusé' },
    },
    // Adresse inconnue : une vraie page plutôt qu'un renvoi silencieux vers l'accueil,
    // qui laisserait croire que le lien fonctionne
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: 'Page introuvable' },
    },
  ],
})

router.beforeEach((to, from) => {
  const user = useUserStore()
  // Compte refusé par l'API : aucune page de données, quel que soit le rôle
  if (user.unlinked) {
    return to.name === 'unlinked-account' ? true : { name: 'unlinked-account', replace: true }
  }
  if (!to.meta.roles || user.hasAnyRole(to.meta.roles)) {
    // Avant le chargement de la page : la vue d'ensemble n'est pas téléchargée
    // si l'arrivée est redirigée.
    return redirectionInitiale(to, from, user.sites, user.roles) ?? true
  }
  return { name: 'access-denied', replace: true }
})

/** Rôle *-SITE sans rôle *-CLIENT : les sites sont ceux de app.utilisateur_site. */
function perimetreSite(roles: readonly string[]) {
  const client = roles.some((role) => ROLES_CLIENT.includes(role as Role))
  const site = roles.some((role) => ROLES_SITE.includes(role as Role))
  return site && !client
}

/**
 * Page d'arrivée (US6) pour un rôle limité à ses sites.
 * Un seul site attribué et une adresse sur la vue d'ensemble : sa page,
 * en gardant la query et le hash. Un rôle *-CLIENT voit tous les sites de
 * son client, même s'il a aussi une ligne dans app.utilisateur_site.
 */
export function routeApresConnexion(
  routeName: string | symbol | null | undefined,
  sites: readonly string[] | null,
  roles: readonly string[],
  query: LocationQuery = {},
  hash = '',
):
  | {
      name: 'sites'
      params: { siteId: string }
      query: LocationQuery
      hash: string
      replace: true
    }
  | undefined {
  const seulSite = sites?.length === 1 ? sites[0] : undefined
  if (routeName === 'overview' && seulSite && perimetreSite(roles)) {
    return { name: 'sites', params: { siteId: seulSite }, query, hash, replace: true }
  }
  return undefined
}

/** Uniquement la première navigation : un clic ultérieur sur « Vue d'ensemble » reste. */
export function redirectionInitiale(
  to: { name?: string | symbol | null; query: LocationQuery; hash: string },
  from: { matched: readonly unknown[] },
  sites: readonly string[] | null,
  roles: readonly string[],
) {
  if (from.matched.length > 0) return undefined
  return routeApresConnexion(to.name, sites, roles, to.query, to.hash)
}

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · EnerVision` : 'EnerVision'
})

export default router
