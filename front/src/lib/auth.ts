import Keycloak, { type KeycloakTokenParsed } from 'keycloak-js'

/** Durée minimale de validité (s) garantie au jeton avant chaque appel à l'API */
const MIN_VALIDITY_S = 30

let keycloak: Keycloak | undefined
const refreshListeners: ((claims: KeycloakTokenParsed) => void)[] = []

/** Adresse de Keycloak : relative au site par défaut, car Traefik sert tout sur la même origine */
export function keycloakUrl(
  configured: string | undefined = import.meta.env.VITE_KEYCLOAK_URL,
  origin: string = window.location.origin,
): string {
  return new URL(configured || '/auth', origin).href.replace(/\/$/, '')
}

function client(): Keycloak {
  if (!keycloak) throw new Error('Authentification non initialisée : appeler initAuth()')
  return keycloak
}

/**
 * Connecte l'utilisateur avant l'affichage de l'application : sans session, redirection vers
 * la page de connexion de Keycloak (flux Authorization Code + PKCE). Le jeton reste en mémoire.
 */
export async function initAuth(): Promise<KeycloakTokenParsed> {
  keycloak = new Keycloak({
    url: keycloakUrl(),
    realm: import.meta.env.VITE_KEYCLOAK_REALM || 'enervision',
    clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'enervision-front',
  })
  keycloak.onTokenExpired = () => {
    client()
      .updateToken(MIN_VALIDITY_S)
      .catch(() => login())
  }
  keycloak.onAuthRefreshSuccess = () => {
    const claims = client().tokenParsed
    if (claims) refreshListeners.forEach((listener) => listener(claims))
  }
  await keycloak.init({ onLoad: 'login-required', pkceMethod: 'S256', checkLoginIframe: false })
  return keycloak.tokenParsed ?? {}
}

/** Appelé à chaque renouvellement du jeton (rôles mis à jour sans recharger la page) */
export function onTokenRefresh(listener: (claims: KeycloakTokenParsed) => void) {
  refreshListeners.push(listener)
}

/** Jeton d'accès valide, renouvelé s'il expire bientôt */
export async function getToken(): Promise<string> {
  const kc = client()
  await kc.updateToken(MIN_VALIDITY_S)
  if (!kc.token) throw new Error('Aucun jeton disponible')
  return kc.token
}

export function login(): Promise<void> {
  return client().login()
}

/** Ferme la session Keycloak et revient à l'accueil, qui redemande la connexion */
export function logout(): Promise<void> {
  return client().logout({ redirectUri: `${window.location.origin}/` })
}
