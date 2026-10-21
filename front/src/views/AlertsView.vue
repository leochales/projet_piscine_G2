<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import AlertsTable from '@/components/alerts/AlertsTable.vue'
import RecommendationItem from '@/components/alerts/RecommendationItem.vue'
import { formatEur } from '@/lib/format'
import { fetchAlerts, fetchPreviousSavings, fetchRecommendations } from '@/services/dashboard'
import { useUserStore } from '@/stores/user'
import type { Alert, Recommendation } from '@/types/energy'

const user = useUserStore()
const { role } = storeToRefs(user)

const alerts = ref<Alert[]>([])
const recommendations = ref<Recommendation[]>([])
const previousSavings = ref(0)

onMounted(async () => {
  ;[alerts.value, recommendations.value, previousSavings.value] = await Promise.all([
    fetchAlerts(),
    fetchRecommendations(),
    fetchPreviousSavings(),
  ])
})

// Pour l'instant, les actions ne sont gardées que dans la page (pas encore d'API)
function acknowledge(alertId: string) {
  const alert = alerts.value.find((a) => a.id === alertId)
  if (alert) alert.priseEnCompte = true
}

function decide(id: string, statut: 'acceptee' | 'refusee') {
  const rec = recommendations.value.find((r) => r.id === id)
  if (rec) rec.statut = statut
}

// Économies = somme des gains des recommandations acceptées
const savings = computed(
  () =>
    previousSavings.value +
    recommendations.value
      .filter((r) => r.statut === 'acceptee')
      .reduce((total, r) => total + r.gainEstimeEur, 0),
)
</script>

<template>
  <section class="space-y-4">
    <h1 class="sr-only">Alertes et recommandations</h1>
    <p v-if="role === 'direction'" class="text-sm text-muted-foreground">
      Lecture seule : les actions sont réservées aux responsables.
    </p>

    <div class="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Alertes actives</CardTitle></CardHeader>
        <CardContent>
          <AlertsTable :alerts="alerts" :can-act-on="user.canActOn" @acknowledge="acknowledge" />
        </CardContent>
      </Card>

      <div class="space-y-4">
        <Card>
          <CardHeader><CardTitle>Recommandations</CardTitle></CardHeader>
          <CardContent class="divide-y">
            <RecommendationItem
              v-for="rec in recommendations"
              :key="rec.id"
              :recommendation="rec"
              :can-act="user.canActOn(rec.siteId)"
              @accept="decide($event, 'acceptee')"
              @refuse="decide($event, 'refusee')"
            />
          </CardContent>
        </Card>

        <Card class="gap-1">
          <CardHeader><CardTitle>Économies réalisées ce mois-ci</CardTitle></CardHeader>
          <CardContent>
            <p class="text-3xl font-semibold tabular-nums">{{ formatEur(savings) }}</p>
            <p class="text-sm text-muted-foreground">
              somme des gains des recommandations acceptées
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  </section>
</template>
