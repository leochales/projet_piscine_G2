<script setup lang="ts">
import { computed } from 'vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatEur } from '@/lib/format'
import type { Recommendation } from '@/types/energy'

const props = defineProps<{
  recommendation: Recommendation
  canAct: boolean
}>()
const emit = defineEmits<{ accept: [id: string]; refuse: [id: string] }>()

const gain = computed(() => {
  const { gainEstimeEur, periodeGain } = props.recommendation
  return `gain estimé : ${formatEur(gainEstimeEur)}${periodeGain === 'semaine' ? ' par semaine' : ''}`
})
</script>

<template>
  <article class="py-3 first:pt-0 last:pb-0">
    <h3 class="font-semibold">{{ recommendation.siteId }} · {{ recommendation.titre }}</h3>
    <p class="text-sm text-muted-foreground">
      <template v-if="recommendation.alerteLiee">
        Liée à l'alerte « {{ recommendation.alerteLiee }} » ·
      </template>
      {{ gain }}
    </p>

    <div class="mt-2">
      <Badge v-if="recommendation.statut === 'acceptee'" variant="secondary">Acceptée</Badge>
      <Badge v-else-if="recommendation.statut === 'refusee'" variant="outline">Refusée</Badge>
      <div v-else-if="canAct" class="flex gap-2">
        <Button size="sm" @click="emit('accept', recommendation.id)">Accepter</Button>
        <Button size="sm" variant="outline" @click="emit('refuse', recommendation.id)">
          Refuser
        </Button>
      </div>
    </div>
  </article>
</template>
