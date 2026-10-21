<script setup lang="ts">
import { computed } from 'vue'

import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { formatPct } from '@/lib/format'

const props = defineProps<{ pourcentage: number }>()

// Au-delà de 85 %, la barre est mise en avant (seuil d'alerte à 90 %)
const high = computed(() => props.pourcentage >= 85)
</script>

<template>
  <div class="flex items-center gap-3">
    <Progress
      :model-value="Math.min(pourcentage, 100)"
      :class="cn('h-2 w-36', high && '[&>[data-slot=progress-indicator]]:bg-foreground')"
      :aria-label="`${formatPct(pourcentage)} de la capacité`"
    />
    <span class="w-12 text-sm tabular-nums" :class="high && 'font-semibold'">
      {{ formatPct(pourcentage) }}
    </span>
  </div>
</template>
