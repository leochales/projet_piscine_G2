import { computed, watch } from 'vue'
import { useDocumentVisibility, useIntervalFn } from '@vueuse/core'

import type { RequestState } from '@/lib/request'

// L'ETL collecte une mesure par minute : rafraîchir plus souvent n'apporterait rien
export const REFRESH_INTERVAL_MS = 60_000

// Seuls l'état et la fraîcheur servent ici, pas les données : des requêtes de types
// différents peuvent être rafraîchies ensemble
type Refreshable = Pick<RequestState<unknown>, 'status' | 'updatedAt' | 'reload'>

/**
 * Rafraîchit les données d'un écran à intervalle régulier.
 *
 * - En pause quand l'onglet n'est pas visible : pas d'appels inutiles à l'API.
 * - Au retour sur l'onglet, rafraîchit tout de suite si les données ont dépassé l'intervalle.
 * - Les données restent affichées pendant le rafraîchissement, et après un échec
 *   (useRequest) : l'écran ne repasse jamais par le squelette.
 *
 * Fraîcheur : l'heure de la plus ancienne des réponses affichées.
 */
export function useAutoRefresh(requests: Refreshable[], intervalMs: number = REFRESH_INTERVAL_MS) {
  const visibility = useDocumentVisibility()

  async function refresh() {
    await Promise.all(requests.map((request) => request.reload()))
  }

  const { pause, resume } = useIntervalFn(() => void refresh(), intervalMs)

  const updatedAt = computed(() => {
    const dates = requests.flatMap((request) => request.updatedAt.value ?? [])
    return dates.length === requests.length
      ? new Date(Math.min(...dates.map((date) => date.getTime())))
      : undefined
  })
  const refreshing = computed(() => requests.some((r) => r.status.value === 'loading'))
  // Échec d'un rafraîchissement : les données affichées sont celles d'avant
  const failed = computed(() => requests.some((r) => r.status.value === 'error'))

  watch(visibility, (state) => {
    if (state === 'hidden') {
      pause()
      return
    }
    resume()
    const last = updatedAt.value
    if (!last || Date.now() - last.getTime() >= intervalMs) void refresh()
  })

  return { refresh, updatedAt, refreshing, failed }
}
