import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  acknowledgeAlert,
  decideRecommendation,
  fetchAlerts,
  fetchPreviousSavings,
  fetchRecommendations,
} from '@/services/dashboard'
import { useUserStore } from '@/stores/user'
import type { Alert, Recommendation } from '@/types/energy'

const WEEKS_PER_MONTH = 52 / 12

/** Gain ramené au mois : un gain hebdomadaire compte pour ~4,3 semaines */
export const monthlyGain = (rec: Recommendation) =>
  rec.periodeGain === 'semaine' ? rec.gainEstimeEur * WEEKS_PER_MONTH : rec.gainEstimeEur

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
  const previousSavings = ref(0)
  const loaded = ref(false)
  // Alertes et recommandations dont l'action est en cours d'envoi : leurs boutons sont bloqués,
  // un double clic n'envoie pas deux fois la même action
  const pending = ref(new Set<string>())

  async function load() {
    if (loaded.value) return
    ;[alerts.value, recommendations.value, previousSavings.value] = await Promise.all([
      fetchAlerts(),
      fetchRecommendations(),
      fetchPreviousSavings(),
    ])
    loaded.value = true
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
      () =>
        Object.assign(alert, {
          priseEnCompte: true,
          prisePar: user.nom,
          priseLe: new Date().toISOString(),
        }),
    )
  }

  async function decide(id: string, statut: 'acceptee' | 'refusee') {
    const rec = recommendations.value.find((r) => r.id === id)
    if (!rec) return
    await send(
      id,
      () => decideRecommendation(id, statut),
      () => (rec.statut = statut),
    )
  }

  // Alertes restant à traiter (non prises en compte)
  const pendingAlerts = computed(() => alerts.value.filter((a) => !a.priseEnCompte))
  const pendingCritical = computed(
    () => pendingAlerts.value.filter((a) => a.gravite === 'critique').length,
  )

  // Économies du mois = déjà réalisées + gains mensuels des recommandations acceptées
  const savings = computed(
    () =>
      previousSavings.value +
      recommendations.value
        .filter((r) => r.statut === 'acceptee')
        .reduce((total, r) => total + monthlyGain(r), 0),
  )

  return {
    alerts,
    recommendations,
    loaded,
    pending,
    load,
    acknowledge,
    decide,
    pendingAlerts,
    pendingCritical,
    savings,
  }
})
