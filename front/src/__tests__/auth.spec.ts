import { describe, expect, it, vi } from 'vitest'

import { getToken, initAuth, keycloakUrl, logout } from '@/lib/auth'

interface FakeKeycloak {
  config: unknown
  init: ReturnType<typeof vi.fn<(options: unknown) => Promise<boolean>>>
  updateToken: ReturnType<typeof vi.fn<(minValidity: number) => Promise<boolean>>>
  logout: ReturnType<typeof vi.fn<(options: unknown) => Promise<void>>>
}

const instances: FakeKeycloak[] = []
const last = () => instances[instances.length - 1]!

vi.mock('keycloak-js', () => ({
  default: vi.fn<(config: unknown) => void>(function (this: Record<string, unknown>, config) {
    this.config = config
    this.init = vi.fn<(options: unknown) => Promise<boolean>>(() => Promise.resolve(true))
    this.updateToken = vi.fn<(minValidity: number) => Promise<boolean>>(() =>
      Promise.resolve(false),
    )
    this.logout = vi.fn<(options: unknown) => Promise<void>>(() => Promise.resolve())
    this.login = vi.fn<() => Promise<void>>(() => Promise.resolve())
    this.token = 'jeton'
    this.tokenParsed = { realm_access: { roles: ['CONSULT-SITE'] } }
    instances.push(this as unknown as FakeKeycloak)
  }),
}))

describe('keycloakUrl', () => {
  it('place Keycloak sous /auth, à la même origine que le front', () => {
    expect(keycloakUrl(undefined, 'https://10.43.43.80:8443')).toBe('https://10.43.43.80:8443/auth')
  })

  it('accepte une adresse complète', () => {
    expect(keycloakUrl('http://localhost/auth/', 'http://localhost:5173')).toBe(
      'http://localhost/auth',
    )
  })
})

describe('initAuth', () => {
  it('exige la connexion avec PKCE et renvoie le contenu du jeton', async () => {
    const claims = await initAuth()

    expect(last().config).toMatchObject({ realm: 'enervision', clientId: 'enervision-front' })
    expect(last().init).toHaveBeenCalledWith(
      expect.objectContaining({ onLoad: 'login-required', pkceMethod: 'S256' }),
    )
    expect(claims.realm_access?.roles).toEqual(['CONSULT-SITE'])
  })

  it('renouvelle le jeton avant de le donner', async () => {
    await initAuth()
    expect(await getToken()).toBe('jeton')
    expect(last().updateToken).toHaveBeenCalledWith(30)
  })

  it('revient à l’accueil après la déconnexion', async () => {
    await initAuth()
    await logout()
    expect(last().logout).toHaveBeenCalledWith({ redirectUri: `${window.location.origin}/` })
  })
})
