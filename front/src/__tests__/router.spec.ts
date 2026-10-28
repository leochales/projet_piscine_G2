import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import router, { redirectionInitiale, routeApresConnexion } from '@/router'
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

  it('à la connexion, un rôle site avec un seul site ouvre sa page', () => {
    const page = {
      name: 'sites' as const,
      params: { siteId: 'SITE002' },
      query: { periode: '7j' },
      hash: '#courbe',
      replace: true as const,
    }
    expect(
      routeApresConnexion('overview', ['SITE002'], ['CONSULT-SITE'], { periode: '7j' }, '#courbe'),
    ).toEqual(page)
    expect(
      routeApresConnexion('overview', ['SITE002'], ['GESTION-SITE'], { periode: '7j' }, '#courbe'),
    ).toEqual(page)
    expect(
      routeApresConnexion('overview', ['SITE002', 'SITE007'], ['CONSULT-SITE']),
    ).toBeUndefined()
    expect(routeApresConnexion('overview', [], ['CONSULT-SITE'])).toBeUndefined()
    expect(routeApresConnexion('overview', null, ['CONSULT-SITE'])).toBeUndefined()
    expect(routeApresConnexion('alerts', ['SITE002'], ['CONSULT-SITE'])).toBeUndefined()
  })

  it('un rôle client reste sur la vue d’ensemble, même avec un site attribué', () => {
    for (const roles of [
      ['GESTION-CLIENT'],
      ['CONSULT-CLIENT'],
      ['GESTION-CLIENT', 'GESTION-SITE'],
    ]) {
      expect(routeApresConnexion('overview', ['SITE002'], roles)).toBeUndefined()
    }
  })

  it('ne redirige que la première navigation, et garde la query', () => {
    const to = { name: 'overview' as const, query: { periode: '7j' }, hash: '#courbe' }
    expect(redirectionInitiale(to, { matched: [] }, ['SITE002'], ['CONSULT-SITE'])).toEqual({
      name: 'sites',
      params: { siteId: 'SITE002' },
      query: { periode: '7j' },
      hash: '#courbe',
      replace: true,
    })
    expect(
      redirectionInitiale(to, { matched: [{}] }, ['SITE002'], ['CONSULT-SITE']),
    ).toBeUndefined()
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
