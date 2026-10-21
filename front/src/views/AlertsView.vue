<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import AlertsTable from '@/components/alerts/AlertsTable.vue'
import RecommendationItem from '@/components/alerts/RecommendationItem.vue'
import { formatEur } from '@/lib/format'
import { useOperationsStore } from '@/stores/operations'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const { role } = storeToRefs(user)

const operations = useOperationsStore()
const { alerts, recommendations, savings } = storeToRefs(operations)

onMounted(() => operations.load())
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
          <AlertsTable
            :alerts="alerts"
            :can-act-on="user.canActOn"
            @acknowledge="operations.acknowledge"
          />
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
              @accept="operations.decide($event, 'acceptee')"
              @refuse="operations.decide($event, 'refusee')"
            />
          </CardContent>
        </Card>

        <Card class="gap-1">
          <CardHeader><CardTitle>Économies réalisées ce mois-ci</CardTitle></CardHeader>
          <CardContent>
            <p class="text-3xl font-semibold tabular-nums">{{ formatEur(savings) }}</p>
            <p class="text-sm text-muted-foreground">
              somme des gains des recommandations acceptées (gains hebdomadaires ramenés au mois)
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  </section>
</template>
