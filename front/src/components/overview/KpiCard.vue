<script setup lang="ts">
import { Card, CardContent } from '@/components/ui/card'

defineProps<{
  label: string
  value: string
  hint?: string
}>()
</script>

<template>
  <Card class="gap-1 py-4">
    <CardContent class="px-4">
      <p class="text-xs font-medium tracking-wide text-muted-foreground uppercase">{{ label }}</p>
      <p class="mt-1 text-2xl font-semibold whitespace-nowrap tabular-nums sm:text-3xl">
        {{ value }}
      </p>
      <p v-if="hint" class="mt-1 text-sm text-muted-foreground">
        <slot name="hint">{{ hint }}</slot>
      </p>
    </CardContent>
  </Card>
</template>
