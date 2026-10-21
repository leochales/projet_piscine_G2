<script setup lang="ts">
import { computed } from 'vue'

import { Badge } from '@/components/ui/badge'
import type { DataQuality } from '@/types/energy'

const props = defineProps<{ qualite: DataQuality }>()

const label = computed(() => {
  switch (props.qualite.statut) {
    case 'bonne':
      return 'bonne'
    case 'partielle':
      return `partielle · ${props.qualite.heuresManquantes} h manquantes`
    case 'mauvaise':
      return 'mauvaise'
  }
  return ''
})
</script>

<template>
  <Badge
    variant="outline"
    :class="{
      'border-dashed': qualite.statut === 'partielle',
      'border-critical text-critical': qualite.statut === 'mauvaise',
    }"
  >
    {{ label }}
  </Badge>
</template>
