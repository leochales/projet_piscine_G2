<script setup lang="ts">
import { storeToRefs } from 'pinia'

import RecommendationItem from '@/components/alerts/RecommendationItem.vue'
import { useDecideRecommendation } from '@/lib/actions'
import { useOperationsStore } from '@/stores/operations'
import { useUserStore } from '@/stores/user'
import type { Recommendation } from '@/types/energy'

// Liste des recommandations de l'écran 3 et de la page d'un site, avec les décisions
defineProps<{ recommendations: Recommendation[] }>()

const user = useUserStore()
const { pending } = storeToRefs(useOperationsStore())
const decide = useDecideRecommendation()

// Rôle de l'utilisateur sur le site de la recommandation (mêmes règles que l'API)
const canAct = (siteId: string) => user.canActOn(siteId)
</script>

<template>
  <div class="divide-y">
    <RecommendationItem
      v-for="rec in recommendations"
      :key="rec.id"
      :recommendation="rec"
      :can-act="canAct(rec.siteId)"
      :pending="pending.has(rec.id)"
      @accept="decide($event, 'acceptee')"
      @refuse="decide($event, 'refusee')"
    />
  </div>
</template>
