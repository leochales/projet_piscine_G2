<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { SEVERITY_LABELS } from '@/lib/labels'
import type { Severity } from '@/types/energy'

defineProps<{ gravite: Severity }>()
</script>

<template>
  <Badge
    variant="outline"
    :class="{
      'border-critical font-semibold text-critical': gravite === 'critique',
      'border-warning text-warning': gravite === 'moyenne',
    }"
  >
    {{ SEVERITY_LABELS[gravite] }}
  </Badge>
</template>
