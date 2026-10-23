<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { RotateCw } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { formatAge, formatClock } from '@/lib/format'
import { cn } from '@/lib/utils'

const props = defineProps<{
  updatedAt?: Date
  refreshing: boolean
  /** Le dernier rafraîchissement a échoué : les données affichées sont plus anciennes */
  failed: boolean
}>()

const emit = defineEmits<{ refresh: [] }>()

// Le libellé « il y a 30 s » avance chaque seconde, sans nouvel appel à l'API
const now = shallowRef(new Date())
useIntervalFn(() => (now.value = new Date()), 1000)

const age = computed(() => (props.updatedAt ? formatAge(props.updatedAt, now.value) : ''))
const exactTime = computed(() => props.updatedAt && formatClock(props.updatedAt))
</script>

<template>
  <div v-if="updatedAt" class="flex items-center gap-1 text-xs text-muted-foreground">
    <span :class="cn('size-2 rounded-full', failed ? 'bg-warning' : 'bg-ok')" aria-hidden="true" />
    <!-- Pas de aria-live : un lecteur d'écran n'a pas à annoncer chaque seconde -->
    <time :datetime="updatedAt.toISOString()" :title="`Dernière mise à jour à ${exactTime}`">
      <template v-if="failed">Actualisation impossible · dernière mise à jour {{ age }}</template>
      <template v-else>Mis à jour {{ age }}</template>
    </time>
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label="Actualiser les données"
      title="Actualiser les données"
      :disabled="refreshing"
      @click="emit('refresh')"
    >
      <RotateCw
        :class="cn(refreshing && 'animate-spin motion-reduce:animate-none')"
        aria-hidden="true"
      />
    </Button>
  </div>
</template>
