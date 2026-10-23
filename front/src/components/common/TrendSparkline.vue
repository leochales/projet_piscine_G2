<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { useElementSize } from '@vueuse/core'

import { sparklinePath, sparklinePoints } from '@/lib/sparkline'

const props = withDefaults(
  defineProps<{
    values: readonly number[]
    /** Largeur maximale ; la courbe se réduit pour tenir dans la place disponible */
    maxWidth?: number
    height?: number
  }>(),
  { maxWidth: 88, height: 32 },
)

// Plus étroite que ça, la forme ne se lit plus : on n'affiche rien plutôt qu'un trait écrasé
const MIN_WIDTH = 40

// La courbe prend la place laissée par la valeur, sans jamais déborder de la carte
const box = useTemplateRef<HTMLElement>('box')
const { width: available } = useElementSize(box)
const width = computed(() => Math.min(props.maxWidth, Math.floor(available.value)))

const points = computed(() => sparklinePoints(props.values, width.value, props.height))
const path = computed(() => sparklinePath(points.value))
// Dernier point marqué : la valeur actuelle, à droite
const last = computed(() => points.value[points.value.length - 1])
</script>

<template>
  <div ref="box" class="flex min-w-0 flex-1 justify-end">
    <!-- Décorative : la tendance est aussi donnée en texte par la carte (lecteurs d'écran) -->
    <svg
      v-if="width >= MIN_WIDTH && path"
      :width="width"
      :height="height"
      :viewBox="`-3 0 ${width + 6} ${height}`"
      class="overflow-visible text-muted-foreground"
      aria-hidden="true"
    >
      <path
        :d="path"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle v-if="last" :cx="last.x" :cy="last.y" r="2.5" class="fill-foreground" />
    </svg>
  </div>
</template>
