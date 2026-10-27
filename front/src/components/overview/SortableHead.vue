<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, ArrowUp, ArrowUpDown } from '@lucide/vue'

import { TableHead } from '@/components/ui/table'
import type { SortDirection } from '@/lib/sites'

const props = defineProps<{
  label: string
  /** Sens du tri si cette colonne est triée, sinon null */
  direction: SortDirection | null
}>()
const emit = defineEmits<{ sort: [] }>()

// aria-sort sur l'en-tête : les lecteurs d'écran annoncent la colonne triée et son sens
const ariaSort = computed(() =>
  props.direction === null ? 'none' : props.direction === 'asc' ? 'ascending' : 'descending',
)
</script>

<template>
  <TableHead :aria-sort="ariaSort">
    <button
      type="button"
      class="-ml-1 inline-flex items-center gap-1 rounded-sm px-1 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      :class="direction !== null && 'text-foreground'"
      @click="emit('sort')"
    >
      {{ label }}
      <ArrowUp v-if="direction === 'asc'" class="size-3.5" aria-hidden="true" />
      <ArrowDown v-else-if="direction === 'desc'" class="size-3.5" aria-hidden="true" />
      <ArrowUpDown v-else class="size-3.5 opacity-40" aria-hidden="true" />
    </button>
  </TableHead>
</template>
