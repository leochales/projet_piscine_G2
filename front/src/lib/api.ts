import { getToken, login } from '@/lib/auth'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message = `Erreur ${status} de l'API`,
  ) {
    super(message)
  }
}

/**
 * Détail du 403 renvoyé par l'API pour un compte Keycloak absent de app.utilisateur
 * (api/auth.py, DETAIL_COMPTE_NON_RATTACHE) : à changer des deux côtés.
 */
export const DETAIL_COMPTE_NON_RATTACHE = 'Compte non rattaché à un client'

const unlinkedListeners: (() => void)[] = []

/** Appelé quand l'API refuse le compte : il n'est rattaché à aucune entreprise */
export function onUnlinkedAccount(listener: () => void) {
  unlinkedListeners.push(listener)
}

/** Le 403 vient-il d'un compte non rattaché (et non d'un rôle insuffisant) ? */
async function isUnlinkedAccount(response: Response): Promise<boolean> {
  try {
    const body: unknown = await response.clone().json()
    return (
      typeof body === 'object' &&
      body !== null &&
      (body as { detail?: unknown }).detail === DETAIL_COMPTE_NON_RATTACHE
    )
  } catch {
    return false
  }
}

/**
 * Appel à l'API avec le jeton de l'utilisateur. Une réponse 401 (session expirée ou jeton
 * refusé) relance la connexion Keycloak. Un 403 « compte non rattaché » prévient l'application
 * (onUnlinkedAccount), qui affiche la page dédiée ; la réponse est renvoyée telle quelle.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
  baseUrl: string = import.meta.env.VITE_API_URL || '/api',
): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${await getToken()}`)
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers })
  if (response.status === 401) {
    await login()
    throw new ApiError(401, 'Session expirée')
  }
  if (response.status === 403 && (await isUnlinkedAccount(response))) {
    unlinkedListeners.forEach((listener) => listener())
  }
  return response
}

export type AccountStatus = 'ok' | 'unlinked' | 'unavailable'

/**
 * Vérifie, juste après la connexion, que l'API accepte le jeton et connaît le compte
 * (GET /api/moi). « unavailable » : API injoignable ou en erreur, l'application démarre
 * quand même et chaque écran affichera ses propres erreurs.
 */
export async function checkAccount(baseUrl?: string): Promise<AccountStatus> {
  try {
    const response = await apiFetch('/moi', { headers: { Accept: 'application/json' } }, baseUrl)
    if (response.ok) return 'ok'
    if (response.status === 403 && (await isUnlinkedAccount(response))) return 'unlinked'
    return 'unavailable'
  } catch (error) {
    // 401 : la connexion est déjà relancée par apiFetch
    if (!(error instanceof ApiError)) console.error('Vérification du compte impossible', error)
    return 'unavailable'
  }
}
