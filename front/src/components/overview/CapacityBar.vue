<script setup lang="ts">
import { computed } from 'vue'
import { TriangleAlert } from '@lucide/vue'

import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { formatPct } from '@/lib/format'
import { capacityLevel } from '@/lib/indicators'

// pourcentage null : le site n'a pas de mesure, la barre n'a pas de sens.
// seuil : seuil d'alerte du site, en % (90 % par défaut, comme lib/indicators.ts)
const props = defineProps<{ pourcentage: number | null; seuil?: number }>()

const level = computed(() =>
  props.pourcentage === null ? null : capacityLevel(props.pourcentage, props.seuil),
)

// La couleur n'est jamais seule : au seuil d'alerte, une icône et le texte en gras s'ajoutent
const indicator = computed(() => {
  if (level.value === 'critique') return '[&>[data-slot=progress-indicator]]:bg-critical'
  if (level.value === 'eleve') return '[&>[data-slot=progress-indicator]]:bg-warning'
  return ''
})

const label = computed(() => {
  if (props.pourcentage === null) return 'Capacité : pas de mesure'
  const pct = `${formatPct(props.pourcentage)} de la capacité`
  return level.value === 'critique' ? `${pct}, seuil d'alerte atteint` : pct
})
</script>

<template>
  <div class="flex items-center gap-3">
    <template v-if="pourcentage !== null">
      <Progress
        :model-value="Math.min(pourcentage, 100)"
        :class="cn('h-2 w-36', indicator)"
        :aria-label="label"
      />
      <span
        class="inline-flex w-16 items-center gap-1 text-sm tabular-nums"
        :class="{
          'font-semibold': level !== 'normal',
          'text-critical': level === 'critique',
        }"
      >
        {{ formatPct(pourcentage) }}
        <TriangleAlert v-if="level === 'critique'" class="size-3.5" aria-hidden="true" />
      </span>
    </template>
    <!-- Même largeur que la barre : les colonnes restent alignées -->
    <span v-else class="w-[13rem] text-sm text-muted-foreground" :aria-label="label">—</span>
  </div>
</template>
