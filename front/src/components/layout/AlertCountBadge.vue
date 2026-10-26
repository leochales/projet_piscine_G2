<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { cn } from '@/lib/utils'
import { useOperationsStore } from '@/stores/operations'

const { pendingAlerts, pendingCritical } = storeToRefs(useOperationsStore())

const count = computed(() => pendingAlerts.value.length)

// Lu par les lecteurs d'écran à la suite du lien : « Alertes et recommandations, 3 à traiter… »
const label = computed(() => {
  const critical = pendingCritical.value
  const detail = critical > 0 ? `, dont ${critical} critique${critical > 1 ? 's' : ''}` : ''
  return `${count.value} à traiter${detail}`
})
</script>

<template>
  <span
    v-if="count > 0"
    :class="
      cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-semibold tabular-nums',
        // Rouge dès qu'une alerte critique attend : c'est l'information la plus urgente
        pendingCritical > 0
          ? 'bg-critical text-primary-foreground'
          : 'bg-secondary text-foreground',
      )
    "
  >
    <span aria-hidden="true">{{ count }}</span>
    <span class="sr-only">{{ label }}</span>
  </span>
</template>
