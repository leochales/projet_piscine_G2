import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import router, { routeApresConnexion } from '@/router'
import { useUserStore } from '@/stores/user'

const signIn = (roles: string[]) =>
  useUserStore().setFromToken({ realm_access: { roles }, email: 'test@example.com' })

describe('protection des routes', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    signIn([])
    await router.replace('/acces-refuse')
  })

  it('laisse passer un rôle de consultation sur les écrans du dashboard', async () => {
    signIn(['CONSULT-SITE'])
    for (const path of ['/', '/sites/SITE002', '/alertes']) {
      await router.push(path)
      expect(router.currentRoute.value.fullPath).toBe(path)
    }
  })

  it('renvoie le monitoring seul vers la page d’accès refusé', async () => {
    signIn(['MONITORING'])
    await router.push('/alertes')
    expect(router.currentRoute.value.name).toBe('access-denied')
  })

  it('renvoie un utilisateur sans rôle vers la page d’accès refusé', async () => {
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('access-denied')
  })

  it('cantonne un compte non rattaché à sa page, même avec un rôle de gestion', async () => {
    signIn(['GESTION-CLIENT'])
    useUserStore().unlinked = true

    for (const path of ['/', '/alertes', '/acces-refuse']) {
      await router.push(path)
      expect(router.currentRoute.value.name).toBe('unlinked-account')
    }
  })

  it('à la connexion, un seul site ouvre sa page, plusieurs restent sur la vue d’ensemble', () => {
    expect(routeApresConnexion('overview', ['SITE002'])).toEqual({
      name: 'sites',
      params: { siteId: 'SITE002' },
    })
    expect(routeApresConnexion('overview', ['SITE002', 'SITE007'])).toBeUndefined()
    expect(routeApresConnexion('overview', [])).toBeUndefined()
    expect(routeApresConnexion('overview', null)).toBeUndefined()
    expect(routeApresConnexion('alerts', ['SITE002'])).toBeUndefined()
  })

  it('un clic ultérieur sur la vue d’ensemble n’y renvoie pas', async () => {
    signIn(['CONSULT-SITE'])
    useUserStore().sites = ['SITE002']
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('overview')
  })

  it('affiche la page introuvable sans exiger de rôle', async () => {
    await router.push('/nimporte/quoi')
    expect(router.currentRoute.value.name).toBe('not-found')
  })
})
