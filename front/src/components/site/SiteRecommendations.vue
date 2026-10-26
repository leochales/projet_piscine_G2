<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import RecommendationList from '@/components/alerts/RecommendationList.vue'
import { currentRecommendations } from '@/lib/recommendations'
import type { RequestState } from '@/lib/request'
import { useOperationsStore } from '@/stores/operations'

// US5 : les recommandations en cours du site choisi (à décider, puis acceptées).
// Le chargement appartient à la page du site, qui le rafraîchit avec le reste (useAutoRefresh).
const props = defineProps<{
  siteId: string
  request: Pick<RequestState<unknown>, 'status' | 'updatedAt' | 'reload'>
}>()

// Même store que l'écran 3 : une décision prise ici s'y voit aussitôt, et inversement
const { recommendations } = storeToRefs(useOperationsStore())
const current = computed(() => currentRecommendations(recommendations.value, props.siteId))

// Squelette au premier chargement seulement : un rafraîchissement garde la liste affichée
const firstLoad = computed(() => !props.request.updatedAt.value)
</script>

<template>
  <Card>
    <CardHeader><CardTitle>Recommandations en cours</CardTitle></CardHeader>
    <CardContent v-if="firstLoad && request.status.value === 'error'">
      <RequestError what="les recommandations" @retry="request.reload" />
    </CardContent>
    <CardContent v-else-if="firstLoad" class="space-y-4" role="status" aria-live="polite">
      <span class="sr-only">Chargement des recommandations…</span>
      <div v-for="n in 2" :key="n" class="space-y-2">
        <Skeleton class="h-4 w-3/4" />
        <Skeleton class="h-4 w-1/2" />
      </div>
    </CardContent>
    <CardContent v-else-if="current.length === 0">
      <EmptyState
        title="Aucune recommandation en cours"
        description="Les recommandations apparaissent quand une alerte ou un pic prévu le justifie."
      />
    </CardContent>
    <CardContent v-else>
      <RecommendationList :recommendations="current" />
    </CardContent>
  </Card>
</template>
