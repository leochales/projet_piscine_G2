import { computed, nextTick } from 'vue'
import { createSharedComposable, useColorMode } from '@vueuse/core'

// Clé du choix dans le localStorage. public/theme-init.js la lit aussi, avant le démarrage de Vue,
// pour appliquer le thème sans flash clair : les deux doivent rester identiques.
export const THEME_STORAGE_KEY = 'enervision-theme'

// Durée du cercle qui révèle le nouveau thème
export const REVEAL_DURATION_MS = 500

// Partagé : un seul état pour toute l'application, quel que soit le composant qui l'utilise.
// useColorMode ajoute ou retire la classe « dark » sur <html> (variante dark de Tailwind,
// couleurs .dark de main.css), et coupe les transitions CSS pendant le changement.
// Tant que l'utilisateur n'a pas cliqué, le thème suit le réglage de l'ordinateur ;
// ensuite, son choix est mémorisé.
export const useTheme = createSharedComposable(() => {
  const mode = useColorMode({ storageKey: THEME_STORAGE_KEY })

  const isDark = computed(() => mode.state.value === 'dark')

  function toggle() {
    mode.store.value = isDark.value ? 'light' : 'dark'
  }

  /**
   * Bascule avec un cercle qui part du point (x, y) et révèle le nouveau thème (View
   * Transitions). Sans cette API, ou si l'utilisateur a demandé à réduire les animations,
   * le changement est immédiat.
   */
  async function toggleFrom(x: number, y: number) {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (!document.startViewTransition || reduceMotion) {
      toggle()
      return
    }

    const transition = document.startViewTransition(async () => {
      toggle()
      await nextTick()
    })
    await transition.ready

    // Rayon jusqu'au coin de l'écran le plus éloigné du bouton
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y))
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      {
        duration: REVEAL_DURATION_MS,
        easing: 'ease-in-out',
        pseudoElement: '::view-transition-new(root)',
      },
    )
  }

  return { isDark, toggle, toggleFrom }
})
