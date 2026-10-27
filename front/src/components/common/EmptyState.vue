<script setup lang="ts">
import { Inbox } from '@lucide/vue'

defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center gap-2 p-6 text-center">
    <Inbox class="size-6 text-muted-foreground" aria-hidden="true" />
    <p class="font-medium">{{ title }}</p>
    <p v-if="description" class="text-sm text-muted-foreground">{{ description }}</p>
  </div>
</template>
