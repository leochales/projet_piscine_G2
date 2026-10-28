// Thème appliqué avant le démarrage de Vue, pour éviter un flash clair. Fichier séparé et
// non script en ligne : la CSP du front (default-src 'self', infra/traefik/dynamic/middlewares.yml)
// refuse les scripts en ligne. Même clé et même règle que src/lib/theme.ts (« auto » ou
// rien : réglage du système).
try {
  var theme = localStorage.getItem('enervision-theme')
  if (theme === 'dark' || ((!theme || theme === 'auto') && matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark')
  }
} catch {}
