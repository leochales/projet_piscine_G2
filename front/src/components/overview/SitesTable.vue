<script setup lang="ts">
import { TriangleAlert } from '@lucide/vue'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import CapacityBar from '@/components/overview/CapacityBar.vue'
import DataQualityBadge from '@/components/overview/DataQualityBadge.vue'
import { formatKw, formatPct, formatRelativeHour } from '@/lib/format'
import { SITE_TYPE_LABELS } from '@/lib/labels'
import type { SiteOverview } from '@/types/energy'

defineProps<{ rows: SiteOverview[] }>()
const emit = defineEmits<{ select: [siteId: string] }>()

const pourcentage = (row: SiteOverview) => (row.consommationKw / row.site.capaciteKw) * 100
</script>

<template>
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Site</TableHead>
        <TableHead>Type</TableHead>
        <TableHead>Consommation actuelle</TableHead>
        <TableHead>% de la capacité</TableHead>
        <TableHead>Pic prévu (48 h)</TableHead>
        <TableHead>Qualité des données</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      <!-- Toute la ligne est cliquable à la souris ; au clavier, c'est le lien de la 1re cellule -->
      <TableRow
        v-for="row in rows"
        :key="row.site.id"
        class="cursor-pointer"
        @click="emit('select', row.site.id)"
      >
        <TableCell class="font-medium">
          <RouterLink
            :to="{ name: 'sites', params: { siteId: row.site.id } }"
            class="rounded-sm hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            @click.stop
          >
            {{ row.site.id }}
          </RouterLink>
        </TableCell>
        <TableCell>{{ SITE_TYPE_LABELS[row.site.type] }}</TableCell>
        <TableCell class="tabular-nums">{{ formatKw(row.consommationKw) }}</TableCell>
        <TableCell><CapacityBar :pourcentage="pourcentage(row)" /></TableCell>
        <TableCell>
          <span v-if="row.picPrevu" class="inline-flex items-center gap-1 font-semibold">
            <TriangleAlert class="size-4" aria-hidden="true" />
            {{ formatRelativeHour(row.picPrevu.horodatage) }} ·
            {{ formatPct(row.picPrevu.pourcentageCapacite) }}
          </span>
          <span v-else class="text-muted-foreground">—</span>
        </TableCell>
        <TableCell><DataQualityBadge :qualite="row.qualite" /></TableCell>
      </TableRow>
    </TableBody>
  </Table>
</template>
