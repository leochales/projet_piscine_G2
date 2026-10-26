<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { Skeleton } from '@/components/ui/skeleton'
import RecommendationList from '@/components/alerts/RecommendationList.vue'
import SiteDataCard from '@/components/site/SiteDataCard.vue'
import { currentRecommendations } from '@/lib/recommendations'
import type { RequestState } from '@/lib/request'
import { useOperationsStore } from '@/stores/operations'

// US5 : les recommandations en cours du site choisi (à décider, puis acceptées).
const props = defineProps<{
  siteId: string
  request: Pick<RequestState<unknown>, 'status' | 'updatedAt' | 'reload'>
}>()

// Même store que l'écran 3 : une décision prise ici s'y voit aussitôt, et inversement
const { recommendations } = storeToRefs(useOperationsStore())
const current = computed(() => currentRecommendations(recommendations.value, props.siteId))
</script>

<template>
  <SiteDataCard
    title="Recommandations en cours"
    what="les recommandations"
    :request="request"
    :empty="current.length === 0"
    empty-title="Aucune recommandation en cours"
    empty-description="Les recommandations apparaissent quand une alerte ou un pic prévu le justifie."
  >
    <template #loading>
      <div class="space-y-4">
        <div v-for="n in 2" :key="n" class="space-y-2">
          <Skeleton class="h-4 w-3/4" />
          <Skeleton class="h-4 w-1/2" />
        </div>
      </div>
    </template>
    <RecommendationList :recommendations="current" />
  </SiteDataCard>
</template>
