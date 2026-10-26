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
 * Appel à l'API avec le jeton de l'utilisateur. Une réponse 401 (session expirée ou jeton
 * refusé) relance la connexion Keycloak.
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
  return response
}
