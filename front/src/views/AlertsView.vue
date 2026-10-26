<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { toast } from 'vue-sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import AlertsTable from '@/components/alerts/AlertsTable.vue'
import RecommendationList from '@/components/alerts/RecommendationList.vue'
import { notifyActionFailed } from '@/lib/actions'
import { alertSites, filterAlerts, NO_FILTER, type AlertFilter } from '@/lib/alerts'
import { formatEur } from '@/lib/format'
import { listedRecommendations } from '@/lib/recommendations'
import { SEVERITY_LABELS } from '@/lib/labels'
import { useRequest } from '@/lib/request'
import { useOperationsStore } from '@/stores/operations'
import { ACTION_ROLES, useUserStore } from '@/stores/user'

const user = useUserStore()
const readOnly = computed(() => !user.hasAnyRole(ACTION_ROLES))

const operations = useOperationsStore()
const { alerts, recommendations, savings, pending } = storeToRefs(operations)
// Même ordre que la page d'un site, sans les recommandations acceptées depuis longtemps
const listed = computed(() => listedRecommendations(recommendations.value))

// Le store ne recharge pas ce qu'il a déjà : revenir sur l'écran garde les actions faites
const request = useRequest(() => operations.load())

// Filtres de la liste des alertes : gravité et site
const filter = ref<AlertFilter>({ ...NO_FILTER })
const filtered = computed(() => filterAlerts(alerts.value, filter.value))
const sites = computed(() => alertSites(alerts.value))
const isFiltered = computed(
  () => filter.value.gravite !== NO_FILTER.gravite || filter.value.siteId !== NO_FILTER.siteId,
)
const severities = Object.keys(SEVERITY_LABELS) as (keyof typeof SEVERITY_LABELS)[]

// En type="single", recliquer sur le bouton actif le désélectionne : on revient à « Toutes »
function setGravite(value: unknown) {
  filter.value.gravite =
    typeof value === 'string' && value !== '' ? (value as AlertFilter['gravite']) : 'toutes'
}
const resetFilter = () => (filter.value = { ...NO_FILTER })

// Retour après chaque action : confirmation discrète, ou erreur à réessayer (lib/actions.ts)
async function acknowledge(alertId: string) {
  const alert = alerts.value.find((a) => a.id === alertId)
  try {
    await operations.acknowledge(alertId)
    toast.success('Alerte prise en compte', {
      description: alert && `${alert.siteId} · ${alert.message}`,
    })
  } catch {
    notifyActionFailed()
  }
}
</script>

<template>
  <section class="space-y-4">
    <h1 class="sr-only">Alertes et recommandations</h1>
    <p v-if="readOnly" class="text-sm text-muted-foreground">
      Lecture seule : les actions sont réservées aux gestionnaires.
    </p>

    <RequestError
      v-if="request.status.value === 'error'"
      what="les alertes et les recommandations"
      @retry="request.reload"
    />

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader class="gap-3">
          <CardTitle>Alertes actives</CardTitle>
          <div v-if="alerts.length > 0" class="flex flex-wrap items-center gap-2">
            <ToggleGroup
              :model-value="filter.gravite"
              type="single"
              variant="outline"
              size="sm"
              aria-label="Filtrer par gravité"
              @update:model-value="setGravite"
            >
              <ToggleGroupItem value="toutes">Toutes</ToggleGroupItem>
              <ToggleGroupItem v-for="g in severities" :key="g" :value="g" class="capitalize">
                {{ SEVERITY_LABELS[g] }}
              </ToggleGroupItem>
            </ToggleGroup>
            <label for="filtre-site" class="sr-only">Filtrer par site</label>
            <select
              id="filtre-site"
              v-model="filter.siteId"
              class="h-8 rounded-md border border-input bg-card px-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <option value="tous">Tous les sites</option>
              <option v-for="siteId in sites" :key="siteId" :value="siteId">{{ siteId }}</option>
            </select>
            <!-- Annoncé quand le nombre change : la liste vient d'être filtrée -->
            <p v-if="isFiltered" class="text-sm text-muted-foreground" aria-live="polite">
              {{ filtered.length }} alerte{{ filtered.length > 1 ? 's' : '' }} sur
              {{ alerts.length }}
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <TableSkeleton v-if="request.status.value === 'loading'" :rows="4" />
          <EmptyState
            v-else-if="alerts.length === 0"
            title="Aucune alerte active"
            description="Tous les sites fonctionnent normalement."
          />
          <div v-else-if="filtered.length === 0" class="flex flex-col items-center">
            <EmptyState
              title="Aucune alerte ne correspond aux filtres"
              description="Modifiez la gravité ou le site choisis."
            />
            <Button variant="outline" size="sm" @click="resetFilter">Effacer les filtres</Button>
          </div>
          <AlertsTable
            v-else
            :alerts="filtered"
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
          <CardContent v-else-if="listed.length === 0">
            <EmptyState
              title="Aucune recommandation"
              description="Les recommandations apparaissent quand une alerte ou un pic prévu le justifie."
            />
          </CardContent>
          <CardContent v-else>
            <RecommendationList :recommendations="listed" />
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
