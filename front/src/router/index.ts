import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: () => import('@/views/OverviewView.vue'),
      meta: { title: "Vue d'ensemble" },
    },
    {
      path: '/sites/:siteId?',
      name: 'sites',
      component: () => import('@/views/SiteDetailView.vue'),
      props: true,
      meta: { title: 'Sites' },
    },
    {
      path: '/alertes',
      name: 'alerts',
      component: () => import('@/views/AlertsView.vue'),
      meta: { title: 'Alertes et recommandations' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · EnerVision` : 'EnerVision'
})

export default router
