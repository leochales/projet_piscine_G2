// Formats français : espaces fines comme séparateur de milliers, virgule décimale

const integer = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const oneDecimal = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })
const euros = new Intl.NumberFormat('fr-FR', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

// null : pas de mesure (capteur en panne). Jamais « 0 kW », qui ferait croire à un site arrêté.
export const formatKw = (kw: number | null) => (kw === null ? '—' : `${integer.format(kw)} kW`)
export const formatEur = (eur: number) => euros.format(eur)
export const formatPct = (pct: number) => `${integer.format(pct)} %`
export const formatTonnes = (t: number) => `${oneDecimal.format(t)} t`

export function formatSignedPct(pct: number) {
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
  return `${sign}${integer.format(Math.abs(pct))} %`
}

// Les dates de l'API sont en UTC. Elles sont toujours affichées à l'heure de Paris, quel que
// soit le fuseau du poste (un navigateur réglé sur un autre fuseau, un serveur en UTC), et
// changements d'heure compris : Intl applique les règles du fuseau à chaque date.
export const TIME_ZONE = 'Europe/Paris'

const parisParts = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: 'numeric',
  hourCycle: 'h23',
})
const weekday = new Intl.DateTimeFormat('fr-FR', { timeZone: TIME_ZONE, weekday: 'short' })
const weekdayAndDay = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TIME_ZONE,
  weekday: 'short',
  day: 'numeric',
})
const clock = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
})

/** Date et heure à Paris, quel que soit le fuseau du poste */
function inParis(date: Date) {
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parisParts.formatToParts(date).find((p) => p.type === type)?.value)
  return { year: part('year'), month: part('month'), day: part('day'), hour: part('hour') }
}

/** Jours calendaires entre deux dates, à Paris (0 : même jour, 1 : lendemain) */
function parisDayDiff(date: Date, now: Date) {
  const d = inParis(date)
  const n = inParis(now)
  return Math.round(
    (Date.UTC(d.year, d.month - 1, d.day) - Date.UTC(n.year, n.month - 1, n.day)) / 86_400_000,
  )
}

/** « demain 14 h », « aujourd'hui 9 h », sinon « jeu. 23 14 h » (heure de Paris) */
export function formatRelativeHour(iso: string, now = new Date()) {
  const date = new Date(iso)
  const hour = `${inParis(date).hour} h`
  const dayDiff = parisDayDiff(date, now)
  if (dayDiff === 0) return `aujourd'hui ${hour}`
  if (dayDiff === 1) return `demain ${hour}`
  return `${weekdayAndDay.format(date)} ${hour}`
}

/** Graduation d'un axe horaire : « jeu. 14 h » (heure de Paris) */
export function formatAxisHour(iso: string) {
  const date = new Date(iso)
  return `${weekday.format(date)} ${inParis(date).hour} h`
}

/** Heure exacte : « 14:05 » (heure de Paris) */
export const formatClock = (date: Date) => clock.format(date)

/** Âge d'une donnée : « à l'instant », « il y a 30 s », « il y a 5 min », « il y a 2 h » */
export function formatAge(from: Date, now = new Date()) {
  const seconds = Math.max(0, Math.floor((now.getTime() - from.getTime()) / 1000))
  if (seconds < 10) return "à l'instant"
  if (seconds < 60) return `il y a ${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `il y a ${minutes} min`
  return `il y a ${Math.floor(minutes / 60)} h`
}
