import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { fetchAlerts, fetchPreviousSavings, fetchRecommendations } from '@/services/dashboard'
import type { Alert, Recommendation } from '@/types/energy'

const WEEKS_PER_MONTH = 52 / 12

/** Gain ramené au mois : un gain hebdomadaire compte pour ~4,3 semaines */
export const monthlyGain = (rec: Recommendation) =>
  rec.periodeGain === 'semaine' ? rec.gainEstimeEur * WEEKS_PER_MONTH : rec.gainEstimeEur

/**
 * Alertes et recommandations, partagées entre la vue d'ensemble et l'écran 3 :
 * une action sur l'une se voit aussitôt sur l'autre.
 * Les actions ne sont gardées qu'en mémoire tant que l'API n'a pas de route pour les enregistrer.
 */
export const useOperationsStore = defineStore('operations', () => {
  const alerts = ref<Alert[]>([])
  const recommendations = ref<Recommendation[]>([])
  const previousSavings = ref(0)
  const loaded = ref(false)

  async function load() {
    if (loaded.value) return
    ;[alerts.value, recommendations.value, previousSavings.value] = await Promise.all([
      fetchAlerts(),
      fetchRecommendations(),
      fetchPreviousSavings(),
    ])
    loaded.value = true
  }

  function acknowledge(alertId: string) {
    const alert = alerts.value.find((a) => a.id === alertId)
    if (alert) alert.priseEnCompte = true
  }

  function decide(id: string, statut: 'acceptee' | 'refusee') {
    const rec = recommendations.value.find((r) => r.id === id)
    if (rec) rec.statut = statut
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
    load,
    acknowledge,
    decide,
    pendingAlerts,
    pendingCritical,
    savings,
  }
})
