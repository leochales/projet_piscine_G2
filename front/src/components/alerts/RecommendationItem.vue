<script setup lang="ts">
import { computed } from 'vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatEur } from '@/lib/format'
import type { Recommendation } from '@/types/energy'

const props = defineProps<{
  recommendation: Recommendation
  canAct: boolean
  /** Décision en cours d'envoi : les deux boutons sont bloqués */
  pending?: boolean
}>()
const emit = defineEmits<{ accept: [id: string]; refuse: [id: string] }>()

const gain = computed(() => {
  const { gainEstimeEur, periodeGain } = props.recommendation
  if (gainEstimeEur === null) return 'gain non estimé'
  return `gain estimé : ${formatEur(gainEstimeEur)}${periodeGain === 'semaine' ? ' par semaine' : ''}`
})
</script>

<template>
  <article class="py-3 first:pt-0 last:pb-0">
    <!-- Action proposée, puis le site concerné (critères de l'US5) -->
    <h3 class="font-semibold">{{ recommendation.titre }}</h3>
    <p class="text-sm">
      <RouterLink
        :to="{ name: 'sites', params: { siteId: recommendation.siteId } }"
        class="hover:underline"
      >
        {{ recommendation.siteId }} · {{ recommendation.nomSite }}
      </RouterLink>
    </p>
    <p v-if="recommendation.description" class="text-sm text-muted-foreground">
      {{ recommendation.description }}
    </p>
    <p class="text-sm text-muted-foreground">
      <template v-if="recommendation.alerteId">Suite à une alerte · </template>
      {{ gain }}
    </p>

    <div class="mt-2">
      <Badge v-if="recommendation.statut === 'acceptee'" variant="secondary">Acceptée</Badge>
      <Badge v-else-if="recommendation.statut === 'refusee'" variant="outline">Refusée</Badge>
      <div v-else-if="canAct" class="flex gap-2">
        <Button size="sm" :disabled="pending" @click="emit('accept', recommendation.id)">
          Accepter
        </Button>
        <Button
          size="sm"
          variant="outline"
          :disabled="pending"
          @click="emit('refuse', recommendation.id)"
        >
          Refuser
        </Button>
      </div>
    </div>
  </article>
</template>
