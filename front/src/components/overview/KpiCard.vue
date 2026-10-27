<script setup lang="ts">
import { ArrowDownRight, ArrowUpRight, Minus, TriangleAlert } from '@lucide/vue'

import { Card, CardContent } from '@/components/ui/card'
import TrendSparkline from '@/components/common/TrendSparkline.vue'
import type { Trend } from '@/lib/indicators'

defineProps<{
  label: string
  value: string
  hint?: string
  /** Sens de la variation donnée dans le hint (« +4 % vs hier ») */
  trend?: Trend
  /** Le hint signale une donnée incomplète : icône d'avertissement et texte mis en avant */
  warning?: boolean
  /** Mini-courbe à droite de la valeur, et sa description pour les lecteurs d'écran */
  sparkline?: readonly (number | null)[]
  sparklineLabel?: string
}>()
</script>

<template>
  <Card class="gap-1 py-4">
    <CardContent class="px-4">
      <p class="text-xs font-medium tracking-wide text-muted-foreground uppercase">{{ label }}</p>
      <!-- La courbe, à droite, prend la place laissée par la valeur. Quand les 5 cartes tiennent
           sur une ligne (lg), la valeur est un peu plus petite pour lui en laisser -->
      <div class="mt-1 flex items-end gap-3">
        <p
          class="shrink-0 text-2xl font-semibold whitespace-nowrap tabular-nums sm:text-3xl lg:text-2xl"
        >
          {{ value }}
        </p>
        <TrendSparkline v-if="sparkline?.length" :values="sparkline" class="mb-1" />
      </div>
      <p v-if="sparkline?.length && sparklineLabel" class="sr-only">{{ sparklineLabel }}</p>
      <p
        v-if="hint"
        class="mt-1 flex items-center gap-1 text-sm"
        :class="warning ? 'font-medium text-foreground' : 'text-muted-foreground'"
      >
        <!-- Orange pour l'icône seulement : en mode clair, il n'est pas assez contrasté pour du
             texte (4,1:1, sous les 4,5:1 du WCAG) -->
        <TriangleAlert v-if="warning" class="size-4 shrink-0 text-warning" aria-hidden="true" />
        <!-- La flèche donne le sens, la couleur dit si c'est une bonne nouvelle -->
        <span
          v-if="trend"
          class="inline-flex"
          :class="{
            'text-ok': trend.favorable === true,
            'text-critical': trend.favorable === false,
          }"
        >
          <ArrowUpRight v-if="trend.direction === 'hausse'" class="size-4" aria-hidden="true" />
          <ArrowDownRight
            v-else-if="trend.direction === 'baisse'"
            class="size-4"
            aria-hidden="true"
          />
          <Minus v-else class="size-4" aria-hidden="true" />
          <span class="sr-only">{{ trend.label }}</span>
        </span>
        <slot name="hint">{{ hint }}</slot>
      </p>
    </CardContent>
  </Card>
</template>
