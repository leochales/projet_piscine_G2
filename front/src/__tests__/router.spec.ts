import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import router from '@/router'
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

  it('affiche la page introuvable sans exiger de rôle', async () => {
    await router.push('/nimporte/quoi')
    expect(router.currentRoute.value.name).toBe('not-found')
  })
})
