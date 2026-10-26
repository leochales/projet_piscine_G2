// Lecture des routes de données de l'API. Chaque appel passe par apiFetch (lib/api.ts) :
// jeton Keycloak ajouté, session expirée (401) et compte non rattaché (403) gérés.
// L'API revérifie le jeton à chaque requête : /api/moi, au démarrage, ne suffit pas.

import { ApiError, apiFetch } from '@/lib/api'

export { ApiError }

type Params = Record<string, string | number | boolean | null | undefined>

/** GET /api{path} ; les paramètres null ou undefined ne sont pas envoyés */
export async function getJson<T>(path: string, params: Params = {}): Promise<T> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) query.set(key, String(value))
  }
  const response = await apiFetch(`${path}${query.size ? `?${query}` : ''}`, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new ApiError(response.status, `API ${path} : erreur ${response.status}`)
  return (await response.json()) as T
}
