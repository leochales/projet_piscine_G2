import { ref, shallowRef, watch, type Ref, type WatchSource } from 'vue'

export type RequestStatus = 'loading' | 'success' | 'error'

export interface RequestState<T> {
  /** Dernière réponse reçue, gardée pendant un rechargement ou après une erreur */
  data: Ref<T | undefined>
  status: Ref<RequestStatus>
  error: Ref<unknown>
  /** Heure de la dernière réponse reçue (fraîcheur des données affichées) */
  updatedAt: Ref<Date | undefined>
  /** Relance l'appel (bouton « Réessayer », rafraîchissement) */
  reload: () => Promise<void>
}

interface RequestOptions {
  /** Relance l'appel quand ces valeurs changent (site, période…) */
  watch?: WatchSource | WatchSource[]
}

/**
 * État d'un appel au service de données : chargement, succès ou erreur.
 *
 * - Les données précédentes restent affichées pendant un rechargement : un rafraîchissement
 *   ne fait pas revenir le squelette de chargement.
 * - Seule la réponse du dernier appel compte : si l'utilisateur change de site pendant un
 *   chargement, la réponse de l'ancien site est ignorée.
 * - Quand les valeurs surveillées changent, les données de l'ancien appel sont effacées :
 *   on n'affiche jamais la courbe d'un site sous le nom d'un autre.
 */
export function useRequest<T>(
  fetcher: () => Promise<T>,
  options: RequestOptions = {},
): RequestState<T> {
  const data = shallowRef<T>()
  const status = ref<RequestStatus>('loading')
  const error = shallowRef<unknown>()
  const updatedAt = shallowRef<Date>()
  let lastCall = 0

  async function reload() {
    const call = ++lastCall
    status.value = 'loading'
    error.value = undefined
    try {
      const result = await fetcher()
      if (call !== lastCall) return
      data.value = result
      updatedAt.value = new Date()
      status.value = 'success'
    } catch (err) {
      if (call !== lastCall) return
      error.value = err
      status.value = 'error'
    }
  }

  if (options.watch) {
    watch(
      options.watch,
      () => {
        data.value = undefined
        updatedAt.value = undefined
        void reload()
      },
      { immediate: true },
    )
  } else {
    void reload()
  }

  return { data, status, error, updatedAt, reload }
}
