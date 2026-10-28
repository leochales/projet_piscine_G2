import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  acknowledgeAlert,
  decideRecommendation,
  fetchAlerts,
  fetchRecommendations,
} from '@/services/dashboard'
import { decidedThisMonth } from '@/lib/recommendations'
import { useUserStore } from '@/stores/user'
import type { Alert, Recommendation } from '@/types/energy'

const WEEKS_PER_MONTH = 52 / 12

/** Gain ramené au mois : un gain hebdomadaire compte pour ~4,3 semaines ; non estimé : 0 */
export function monthlyGain(rec: Recommendation) {
  const gain = rec.gainEstimeEur ?? 0
  return rec.periodeGain === 'semaine' ? gain * WEEKS_PER_MONTH : gain
}

/**
 * Alertes et recommandations, partagées entre la vue d'ensemble et l'écran 3 :
 * une action sur l'une se voit aussitôt sur l'autre.
 * Les actions ne sont gardées qu'en mémoire tant que l'API n'a pas de route pour les enregistrer.
 *
 * Une action n'est affichée qu'une fois confirmée par le service : en cas d'échec, l'état reste
 * celui d'avant et l'erreur remonte à l'écran, qui l'affiche.
 */
export const useOperationsStore = defineStore('operations', () => {
  const alerts = ref<Alert[]>([])
  const recommendations = ref<Recommendation[]>([])
  const loaded = ref(false)
  // Alertes et recommandations dont l'action est en cours d'envoi : leurs boutons sont bloqués,
  // un double clic n'envoie pas deux fois la même action
  const pending = ref(new Set<string>())
  // Décisions confirmées pendant la session, avec leur date : un rechargement des
  // recommandations ne les annule pas (tant que l'API ne les enregistre pas, US7)
  const decisions = new Map<string, Pick<Recommendation, 'statut' | 'decideeLe'>>()

  const withDecisions = (list: Recommendation[]) =>
    list.map((r) => {
      const decision = decisions.get(r.id)
      return decision ? { ...r, ...decision } : r
    })

  // Numéro du dernier chargement des recommandations lancé : une réponse arrivée après une
  // plus récente (rafraîchissement automatique et bouton en même temps) est ignorée
  let recommendationsRequest = 0

  async function fetchLatestRecommendations(): Promise<Recommendation[] | undefined> {
    const request = ++recommendationsRequest
    const list = await fetchRecommendations()
    return request === recommendationsRequest ? withDecisions(list) : undefined
  }

  // Prises en compte confirmées pendant la session : un rechargement des alertes ne les
  // annule pas (tant que l'API ne les enregistre pas, US7)
  const acknowledgments = new Map<string, Pick<Alert, 'priseEnCompte' | 'prisePar' | 'priseLe'>>()

  const withAcknowledgments = (list: Alert[]) =>
    list.map((a) => {
      const acknowledgment = acknowledgments.get(a.id)
      return acknowledgment ? { ...a, ...acknowledgment } : a
    })

  // Même principe que pour les recommandations : seule la réponse la plus récente compte
  let alertsRequest = 0

  async function fetchLatestAlerts(): Promise<Alert[] | undefined> {
    const request = ++alertsRequest
    const list = await fetchAlerts()
    if (request !== alertsRequest) return undefined
    // Alerte terminée (absente de la réponse) : sa prise en compte locale est oubliée, pour
    // qu'une alerte rouverte plus tard sous le même identifiant ne paraisse pas déjà prise
    const ids = new Set(list.map((a) => a.id))
    for (const id of acknowledgments.keys()) if (!ids.has(id)) acknowledgments.delete(id)
    return withAcknowledgments(list)
  }

  // Chargement en cours : l'en-tête et l'écran le demandent au même moment, une seule
  // requête part, et une réponse tardive n'écrase pas une action faite entre-temps
  let loading: Promise<void> | null = null

  function load(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    loading ??= (async () => {
      try {
        const [alertList, recommendationList] = await Promise.all([
          fetchLatestAlerts(),
          fetchLatestRecommendations(),
        ])
        if (alertList) alerts.value = alertList
        if (recommendationList) recommendations.value = recommendationList
        loaded.value = true
      } finally {
        loading = null
      }
    })()
    return loading
  }

  /**
   * Recharge les recommandations seules (page d'un site, et son rafraîchissement) : une
   * panne des alertes n'empêche pas d'afficher les recommandations.
   */
  async function reloadRecommendations() {
    const list = await fetchLatestRecommendations()
    if (list) recommendations.value = list
  }

  /**
   * Recharge les alertes seules (page d'un site, et son rafraîchissement) : un nouveau
   * dépassement de seuil apparaît sans recharger la page (US3).
   */
  async function reloadAlerts() {
    const list = await fetchLatestAlerts()
    if (list) alerts.value = list
  }

  /** Envoie l'action une seule fois à la fois par élément ; l'erreur est relancée à l'appelant */
  async function send(id: string, action: () => Promise<unknown>, apply: () => void) {
    if (pending.value.has(id)) return
    pending.value.add(id)
    try {
      await action()
      apply()
    } finally {
      pending.value.delete(id)
    }
  }

  async function acknowledge(alertId: string) {
    const alert = alerts.value.find((a) => a.id === alertId)
    // Une alerte prise en compte le reste : pas de deuxième prise en compte (US7)
    if (!alert || alert.priseEnCompte) return
    // Qui et quand : affiché sous l'alerte pour tous ceux qui suivent le site
    const user = useUserStore()
    await send(
      alertId,
      () => acknowledgeAlert(alertId),
      () => {
        const acknowledgment = {
          priseEnCompte: true,
          prisePar: user.nom,
          priseLe: new Date().toISOString(),
        }
        acknowledgments.set(alertId, acknowledgment)
        // Cherchée à nouveau : la liste a pu être rechargée pendant l'envoi
        const current = alerts.value.find((a) => a.id === alertId)
        if (current) Object.assign(current, acknowledgment)
      },
    )
  }

  async function decide(id: string, statut: 'acceptee' | 'refusee') {
    if (!recommendations.value.some((r) => r.id === id)) return
    await send(
      id,
      () => decideRecommendation(id, statut),
      () => {
        const decision = { statut, decideeLe: new Date().toISOString() }
        decisions.set(id, decision)
        // Cherchée à nouveau : la liste a pu être rechargée pendant l'envoi
        const rec = recommendations.value.find((r) => r.id === id)
        if (rec) Object.assign(rec, decision)
      },
    )
  }

  // Alertes restant à traiter (non prises en compte)
  const pendingAlerts = computed(() => alerts.value.filter((a) => !a.priseEnCompte))
  const pendingCritical = computed(
    () => pendingAlerts.value.filter((a) => a.gravite === 'critique').length,
  )

  // Économies du mois : gains des recommandations acceptées depuis le 1er (un gain
  // hebdomadaire est ramené au mois). Une acceptée un mois précédent ne compte plus.
  const savings = computed(() =>
    recommendations.value
      .filter((r) => r.statut === 'acceptee' && decidedThisMonth(r))
      .reduce((total, r) => total + monthlyGain(r), 0),
  )

  return {
    alerts,
    recommendations,
    loaded,
    pending,
    load,
    reloadRecommendations,
    reloadAlerts,
    acknowledge,
    decide,
    pendingAlerts,
    pendingCritical,
    savings,
  }
})
