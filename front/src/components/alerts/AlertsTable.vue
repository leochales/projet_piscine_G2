<script setup lang="ts">
import { Check } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import SeverityBadge from '@/components/alerts/SeverityBadge.vue'
import type { Alert } from '@/types/energy'

defineProps<{
  alerts: Alert[]
  canActOn: (siteId: string) => boolean
}>()
const emit = defineEmits<{ acknowledge: [alertId: string] }>()
</script>

<template>
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Gravité</TableHead>
        <TableHead>Site</TableHead>
        <TableHead>Alerte</TableHead>
        <TableHead><span class="sr-only">Action</span></TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      <TableRow v-for="alert in alerts" :key="alert.id">
        <TableCell><SeverityBadge :gravite="alert.gravite" /></TableCell>
        <TableCell>{{ alert.siteId }}</TableCell>
        <TableCell class="whitespace-normal">{{ alert.message }}</TableCell>
        <TableCell class="text-right">
          <span
            v-if="alert.priseEnCompte"
            class="inline-flex items-center gap-1 text-sm text-muted-foreground"
          >
            <Check class="size-4" aria-hidden="true" /> Prise en compte
          </span>
          <Button
            v-else-if="canActOn(alert.siteId)"
            variant="outline"
            size="sm"
            @click="emit('acknowledge', alert.id)"
          >
            Prise en compte
          </Button>
        </TableCell>
      </TableRow>
      <TableEmpty v-if="alerts.length === 0" :colspan="4">Aucune alerte active</TableEmpty>
    </TableBody>
  </Table>
</template>
