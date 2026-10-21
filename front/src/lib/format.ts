// Formats français : espaces fines comme séparateur de milliers, virgule décimale

const integer = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const oneDecimal = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })
const euros = new Intl.NumberFormat('fr-FR', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

export const formatKw = (kw: number) => `${integer.format(kw)} kW`
export const formatEur = (eur: number) => euros.format(eur)
export const formatPct = (pct: number) => `${integer.format(pct)} %`
export const formatTonnes = (t: number) => `${oneDecimal.format(t)} t`

export function formatSignedPct(pct: number) {
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
  return `${sign}${integer.format(Math.abs(pct))} %`
}

/** « demain 14 h », « aujourd'hui 9 h », sinon « jeu. 23 14 h » */
export function formatRelativeHour(iso: string, now = new Date()) {
  const date = new Date(iso)
  const hour = `${date.getHours()} h`
  const dayDiff = Math.round((startOfDay(date).getTime() - startOfDay(now).getTime()) / 86_400_000)
  if (dayDiff === 0) return `aujourd'hui ${hour}`
  if (dayDiff === 1) return `demain ${hour}`
  const day = date.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric' })
  return `${day} ${hour}`
}

function startOfDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}
