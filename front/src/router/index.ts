import { createRouter, createWebHistory } from 'vue-router'

import { DASHBOARD_ROLES, useUserStore } from '@/stores/user'

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

router.beforeEach((to) => {
  if (!to.meta.roles || useUserStore().hasAnyRole(to.meta.roles)) return true
  return { name: 'access-denied', replace: true }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · EnerVision` : 'EnerVision'
})

export default router
