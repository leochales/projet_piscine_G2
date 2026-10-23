<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { toast } from 'vue-sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import AlertsTable from '@/components/alerts/AlertsTable.vue'
import RecommendationItem from '@/components/alerts/RecommendationItem.vue'
import { formatEur } from '@/lib/format'
import { useRequest } from '@/lib/request'
import { useOperationsStore } from '@/stores/operations'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const { role } = storeToRefs(user)

const operations = useOperationsStore()
const { alerts, recommendations, savings, pending } = storeToRefs(operations)

// Le store ne recharge pas ce qu'il a déjà : revenir sur l'écran garde les actions faites
const request = useRequest(() => operations.load())

// Retour après chaque action : confirmation discrète, ou erreur à réessayer.
// Rien n'est affiché comme fait tant que le service ne l'a pas confirmé (store).
const actionFailed = () =>
  toast.error('Action impossible', {
    description: 'Le service de données ne répond pas. Réessayez dans un instant.',
  })

async function acknowledge(alertId: string) {
  const alert = alerts.value.find((a) => a.id === alertId)
  try {
    await operations.acknowledge(alertId)
    toast.success('Alerte prise en compte', {
      description: alert && `${alert.siteId} · ${alert.message}`,
    })
  } catch {
    actionFailed()
  }
}

async function decide(id: string, statut: 'acceptee' | 'refusee') {
  const rec = recommendations.value.find((r) => r.id === id)
  try {
    await operations.decide(id, statut)
    toast.success(statut === 'acceptee' ? 'Recommandation acceptée' : 'Recommandation refusée', {
      description: rec && `${rec.siteId} · ${rec.titre}`,
    })
  } catch {
    actionFailed()
  }
}
</script>

<template>
  <section class="space-y-4">
    <h1 class="sr-only">Alertes et recommandations</h1>
    <p v-if="role === 'direction'" class="text-sm text-muted-foreground">
      Lecture seule : les actions sont réservées aux responsables.
    </p>

    <RequestError
      v-if="request.status.value === 'error'"
      what="les alertes et les recommandations"
      @retry="request.reload"
    />

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Alertes actives</CardTitle></CardHeader>
        <CardContent>
          <TableSkeleton v-if="request.status.value === 'loading'" :rows="4" />
          <EmptyState
            v-else-if="alerts.length === 0"
            title="Aucune alerte active"
            description="Tous les sites fonctionnent normalement."
          />
          <AlertsTable
            v-else
            :alerts="alerts"
            :can-act-on="user.canActOn"
            :pending="pending"
            @acknowledge="acknowledge"
          />
        </CardContent>
      </Card>

      <div class="space-y-4">
        <Card>
          <CardHeader><CardTitle>Recommandations</CardTitle></CardHeader>
          <CardContent v-if="request.status.value === 'loading'" class="space-y-4">
            <div v-for="n in 3" :key="n" class="space-y-2">
              <Skeleton class="h-4 w-3/4" />
              <Skeleton class="h-4 w-1/2" />
            </div>
          </CardContent>
          <CardContent v-else-if="recommendations.length === 0">
            <EmptyState
              title="Aucune recommandation"
              description="Les recommandations apparaissent quand une alerte ou un pic prévu le justifie."
            />
          </CardContent>
          <CardContent v-else class="divide-y">
            <RecommendationItem
              v-for="rec in recommendations"
              :key="rec.id"
              :recommendation="rec"
              :can-act="user.canActOn(rec.siteId)"
              :pending="pending.has(rec.id)"
              @accept="decide($event, 'acceptee')"
              @refuse="decide($event, 'refusee')"
            />
          </CardContent>
        </Card>

        <Card class="gap-1">
          <CardHeader><CardTitle>Économies réalisées ce mois-ci</CardTitle></CardHeader>
          <CardContent>
            <Skeleton v-if="request.status.value === 'loading'" class="h-9 w-32" />
            <p v-else class="text-3xl font-semibold tabular-nums">{{ formatEur(savings) }}</p>
            <p class="text-sm text-muted-foreground">
              somme des gains des recommandations acceptées (gains hebdomadaires ramenés au mois)
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  </section>
</template>
