<script setup lang="ts">
import { CircleAlert, RotateCw } from '@lucide/vue'

import { Button } from '@/components/ui/button'

defineProps<{
  /** Ce qui n'a pas pu être chargé : « les sites », « la courbe »… */
  what: string
}>()

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div
    role="alert"
    class="flex flex-col items-center gap-3 rounded-lg border border-dashed border-critical/40 p-6 text-center"
  >
    <CircleAlert class="size-6 text-critical" aria-hidden="true" />
    <div>
      <p class="font-medium">Impossible de charger {{ what }}.</p>
      <p class="text-sm text-muted-foreground">
        Le service de données ne répond pas. Réessayez dans un instant.
      </p>
    </div>
    <Button variant="outline" size="sm" @click="emit('retry')">
      <RotateCw aria-hidden="true" />
      Réessayer
    </Button>
  </div>
</template>
