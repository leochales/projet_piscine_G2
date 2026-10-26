// Appels à l'API du dashboard. En dev, /api passe par le proxy de Vite (vite.config.ts),
// en production par Traefik : même adresse que le front, pas de CORS.
// Le jeton Keycloak sera ajouté ici avec la connexion du front (SMARTOPS-85).

export class ApiError extends Error {
  constructor(
    readonly status: number,
    path: string,
  ) {
    super(`API ${path} : erreur ${status}`)
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

/** GET /api{path} ; les paramètres null ou undefined ne sont pas envoyés */
export async function getJson<T>(path: string, params: Params = {}): Promise<T> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) query.set(key, String(value))
  }
  const url = `/api${path}${query.size ? `?${query}` : ''}`
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new ApiError(response.status, path)
  return (await response.json()) as T
}
