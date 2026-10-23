<script setup lang="ts">
import { ArrowDownRight, ArrowUpRight, Minus, TriangleAlert } from '@lucide/vue'

import { Card, CardContent } from '@/components/ui/card'
import type { Trend } from '@/lib/indicators'

defineProps<{
  label: string
  value: string
  hint?: string
  /** Sens de la variation donnée dans le hint (« +4 % vs hier ») */
  trend?: Trend
  /** Le hint signale une donnée incomplète : icône d'avertissement et texte mis en avant */
  warning?: boolean
}>()
</script>

<template>
  <Card class="gap-1 py-4">
    <CardContent class="px-4">
      <p class="text-xs font-medium tracking-wide text-muted-foreground uppercase">{{ label }}</p>
      <p class="mt-1 text-2xl font-semibold whitespace-nowrap tabular-nums sm:text-3xl">
        {{ value }}
      </p>
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
