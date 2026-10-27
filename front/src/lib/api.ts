import { getToken, login } from '@/lib/auth'
import type { MoiApi } from '@/types/api'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message = `Erreur ${status} de l'API`,
  ) {
    super(message)
  }
}

/**
 * En-tête et code ajoutés par l'API au 403 d'un compte Keycloak absent de app.utilisateur
 * (api/auth.py, ENTETE_ERREUR et CODE_COMPTE_NON_RATTACHE) : un code stable, indépendant du
 * message affiché, qui peut changer.
 */
export const ENTETE_ERREUR = 'X-Erreur'
export const CODE_COMPTE_NON_RATTACHE = 'compte-non-rattache'

const unlinkedListeners = new Set<() => void>()

/**
 * Appelé quand l'API refuse le compte : il n'est rattaché à aucune entreprise.
 * Renvoie la fonction qui retire l'écouteur.
 */
export function onUnlinkedAccount(listener: () => void): () => void {
  unlinkedListeners.add(listener)
  return () => unlinkedListeners.delete(listener)
}

const accountListeners = new Set<(moi: MoiApi) => void>()

/**
 * Appelé avec le compte renvoyé par /api/moi (sites attribués compris) quand l'API le
 * reconnaît. Renvoie la fonction qui retire l'écouteur.
 */
export function onAccountChecked(listener: (moi: MoiApi) => void): () => void {
  accountListeners.add(listener)
  return () => accountListeners.delete(listener)
}

/** Le 403 vient-il d'un compte non rattaché (et non d'un rôle insuffisant) ? */
const isUnlinkedAccount = (response: Response) =>
  response.status === 403 && response.headers.get(ENTETE_ERREUR) === CODE_COMPTE_NON_RATTACHE

/**
 * Appel à l'API avec le jeton de l'utilisateur. Une réponse 401 (session expirée ou jeton
 * refusé) relance la connexion Keycloak. Un 403 « compte non rattaché » prévient l'application
 * (onUnlinkedAccount), qui affiche la page dédiée ; la réponse est renvoyée telle quelle.
 * Un init.signal (AbortController) permet d'abandonner l'appel.
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
  if (isUnlinkedAccount(response)) unlinkedListeners.forEach((listener) => listener())
  return response
}

export type AccountStatus = 'ok' | 'unlinked' | 'unavailable'

/** Attente maximale de /api/moi : l'application ne s'affiche qu'après cette vérification */
export const CHECK_ACCOUNT_TIMEOUT_MS = 5000

/**
 * Vérifie, juste après la connexion, que l'API accepte le jeton et connaît le compte
 * (GET /api/moi). « unavailable » : API injoignable, en erreur ou trop lente, l'application
 * démarre quand même et chaque écran affichera ses propres erreurs.
 */
export async function checkAccount(
  baseUrl?: string,
  timeoutMs: number = CHECK_ACCOUNT_TIMEOUT_MS,
): Promise<AccountStatus> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await apiFetch(
      '/moi',
      { headers: { Accept: 'application/json' }, signal: controller.signal },
      baseUrl,
    )
    if (response.ok) {
      const moi = (await response.json()) as MoiApi
      accountListeners.forEach((listener) => listener(moi))
      return 'ok'
    }
    return isUnlinkedAccount(response) ? 'unlinked' : 'unavailable'
  } catch (error) {
    // 401 : la connexion est déjà relancée par apiFetch
    if (!(error instanceof ApiError)) console.error('Vérification du compte impossible', error)
    return 'unavailable'
  } finally {
    clearTimeout(timer)
  }
}
