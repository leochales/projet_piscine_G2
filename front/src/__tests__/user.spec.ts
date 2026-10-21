import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useUserStore } from '@/stores/user'

describe('useUserStore.canActOn', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('le responsable énergie agit sur tous les sites', () => {
    const user = useUserStore()
    expect(user.canActOn('SITE003')).toBe(true)
  })

  it('le responsable de site agit seulement sur ses sites', () => {
    const user = useUserStore()
    user.role = 'site_manager'
    user.siteIds = ['SITE002']
    expect(user.canActOn('SITE002')).toBe(true)
    expect(user.canActOn('SITE003')).toBe(false)
  })

  it('la direction est en lecture seule', () => {
    const user = useUserStore()
    user.role = 'direction'
    expect(user.canActOn('SITE002')).toBe(false)
  })
})
