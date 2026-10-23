<script setup lang="ts">
import { Skeleton } from '@/components/ui/skeleton'

withDefaults(defineProps<{ rows?: number }>(), { rows: 7 })
</script>

<template>
  <!-- Même hauteur de lignes que les tableaux : pas de saut de mise en page à l'arrivée -->
  <div class="space-y-1 p-2" role="status" aria-live="polite">
    <span class="sr-only">Chargement…</span>
    <Skeleton class="mb-3 h-4 w-2/3" />
    <div v-for="n in rows" :key="n" class="flex items-center gap-4 py-2">
      <Skeleton class="h-4 w-20" />
      <Skeleton class="h-4 w-16" />
      <Skeleton class="h-4 flex-1" />
      <Skeleton class="h-4 w-16" />
    </div>
  </div>
</template>
