import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

// useTheme est partagé : le module est rechargé à chaque test pour repartir d'un état neuf
async function loadTheme() {
  vi.resetModules()
  return import('../lib/theme')
}

// jsdom n'implémente pas matchMedia : on simule les réglages du système
function systemPrefers({ dark = false, reducedMotion = false } = {}) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches:
        (dark && query === '(prefers-color-scheme: dark)') ||
        (reducedMotion && query === '(prefers-reduced-motion: reduce)'),
      media: query,
      addEventListener: vi.fn<() => void>(),
      removeEventListener: vi.fn<() => void>(),
    })),
  )
}

// jsdom n'implémente pas non plus les View Transitions ni element.animate
function stubViewTransitions() {
  const animate = vi.fn<Element['animate']>()
  document.documentElement.animate = animate
  const start = vi.fn<(update: () => Promise<void>) => { ready: Promise<void> }>((update) => ({
    ready: update(),
  }))
  Object.assign(document, { startViewTransition: start })
  return { start, animate }
}

const html = document.documentElement

beforeEach(() => {
  localStorage.clear()
  html.className = ''
})

afterEach(() => {
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'startViewTransition')
})

describe('useTheme', () => {
  it('suit le système tant que l’utilisateur n’a pas choisi', async () => {
    systemPrefers({ dark: true })
    const { useTheme } = await loadTheme()
    await nextTick()

    expect(useTheme().isDark.value).toBe(true)
    expect(html.classList.contains('dark')).toBe(true)
  })

  it('bascule au clic et mémorise le choix', async () => {
    systemPrefers()
    const { useTheme, THEME_STORAGE_KEY } = await loadTheme()
    const { isDark, toggle } = useTheme()

    toggle()
    await nextTick()
    expect(isDark.value).toBe(true)
    expect(html.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')

    toggle()
    await nextTick()
    expect(isDark.value).toBe(false)
    expect(html.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })

  it('reprend le choix mémorisé, même si le système dit le contraire', async () => {
    systemPrefers({ dark: true })
    localStorage.setItem('enervision-theme', 'light')
    const { useTheme } = await loadTheme()
    await nextTick()

    expect(useTheme().isDark.value).toBe(false)
    expect(html.classList.contains('dark')).toBe(false)
  })

  it('partage le même état entre les composants', async () => {
    systemPrefers()
    const { useTheme } = await loadTheme()

    useTheme().toggle()
    expect(useTheme().isDark.value).toBe(true)
  })
})

describe('toggleFrom (cercle animé)', () => {
  it('révèle le nouveau thème par un cercle qui part du bouton', async () => {
    systemPrefers()
    const { start, animate } = stubViewTransitions()
    const { useTheme, REVEAL_DURATION_MS } = await loadTheme()

    await useTheme().toggleFrom(100, 20)

    expect(start).toHaveBeenCalledOnce()
    expect(useTheme().isDark.value).toBe(true)
    const [keyframes, options] = animate.mock.calls[0]!
    expect((keyframes as { clipPath: string[] }).clipPath[0]).toBe('circle(0px at 100px 20px)')
    expect(options).toMatchObject({
      duration: REVEAL_DURATION_MS,
      pseudoElement: '::view-transition-new(root)',
    })
  })

  it('bascule sans animation si le navigateur ne connaît pas les View Transitions', async () => {
    systemPrefers()
    const { useTheme } = await loadTheme()

    await useTheme().toggleFrom(100, 20)
    expect(useTheme().isDark.value).toBe(true)
  })

  it('bascule sans animation si l’utilisateur demande à réduire les animations', async () => {
    systemPrefers({ reducedMotion: true })
    const { start } = stubViewTransitions()
    const { useTheme } = await loadTheme()

    await useTheme().toggleFrom(100, 20)
    expect(start).not.toHaveBeenCalled()
    expect(useTheme().isDark.value).toBe(true)
  })
})
