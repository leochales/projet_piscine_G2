import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { DASHBOARD_ROLES, useUserStore } from '@/stores/user'

const token = (roles: string[], extra: Record<string, unknown> = {}) => ({
  realm_access: { roles },
  email: 'marie.martin@client.fr',
  ...extra,
})

describe('useUserStore', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('lit les rôles du jeton et ignore ceux qui ne sont pas des rôles EnerVision', () => {
    const user = useUserStore()
    user.setFromToken(token(['CONSULT-SITE', 'offline_access', 'default-roles-enervision']))
    expect(user.roles).toEqual(['CONSULT-SITE'])
    expect(user.hasAnyRole(DASHBOARD_ROLES)).toBe(true)
  })

  it('prend le nom complet du jeton, sinon prénom et nom, sinon l’e-mail', () => {
    const user = useUserStore()
    user.setFromToken(token([], { name: 'Marie Martin' }))
    expect(user.nom).toBe('Marie Martin')
    user.setFromToken(token([], { given_name: 'Marie', family_name: 'Martin' }))
    expect(user.nom).toBe('Marie Martin')
    user.setFromToken(token([]))
    expect(user.nom).toBe('marie.martin@client.fr')
  })

  it('affiche le rôle le plus large', () => {
    const user = useUserStore()
    user.setFromToken(token(['CONSULT-SITE', 'GESTION-CLIENT']))
    expect(user.roleLabel).toBe('Gestion client')
    user.setFromToken(token([]))
    expect(user.roleLabel).toBe('Aucun rôle')
  })

  it('GESTION-CLIENT agit sur tous les sites du client', () => {
    const user = useUserStore()
    user.setFromToken(token(['GESTION-CLIENT']))
    expect(user.canActOn('SITE002')).toBe(true)
    expect(user.canActOn('SITE007')).toBe(true)
  })

  it('GESTION-SITE agit seulement sur ses sites attribués (GET /api/moi)', () => {
    const user = useUserStore()
    user.setFromToken(token(['GESTION-SITE']))
    // Sites pas encore connus : aucune action proposée
    expect(user.canActOn('SITE002')).toBe(false)

    user.sites = ['SITE002', 'SITE007']
    expect(user.canActOn('SITE002')).toBe(true)
    expect(user.canActOn('SITE001')).toBe(false)
  })

  it('un rôle de consultation ne gère pas ses sites attribués', () => {
    const user = useUserStore()
    user.setFromToken(token(['CONSULT-SITE']))
    user.sites = ['SITE002']
    expect(user.canActOn('SITE002')).toBe(false)
  })

  it('les rôles de consultation et le monitoring sont en lecture seule', () => {
    const user = useUserStore()
    for (const role of ['CONSULT-CLIENT', 'CONSULT-SITE', 'MONITORING']) {
      user.setFromToken(token([role]))
      expect(user.canActOn('SITE002')).toBe(false)
    }
  })

  it('le monitoring seul ne donne pas accès au dashboard', () => {
    const user = useUserStore()
    user.setFromToken(token(['MONITORING']))
    expect(user.hasAnyRole(DASHBOARD_ROLES)).toBe(false)
  })
})
