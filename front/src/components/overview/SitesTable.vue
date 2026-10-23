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
import { capacityPct } from '@/lib/indicators'
import { SITE_TYPE_LABELS } from '@/lib/labels'
import type { SiteOverview } from '@/types/energy'

defineProps<{ rows: SiteOverview[] }>()
const emit = defineEmits<{ select: [siteId: string] }>()

// « — » sans mesure : la raison est donnée au survol et aux lecteurs d'écran
const noReading = 'Pas de mesure : capteur de consommation en panne'

const pourcentage = (row: SiteOverview) => capacityPct(row.consommationKw, row.site.capaciteKw)
</script>

<template>
  <!-- Écran étroit (sous 640 px) : une carte par site, les 6 colonnes ne tiendraient pas -->
  <ul class="divide-y sm:hidden">
    <li v-for="row in rows" :key="row.site.id" class="relative space-y-2 px-2 py-3">
      <div class="flex items-center justify-between gap-2">
        <p>
          <!-- after:inset-0 : le lien couvre toute la carte, qui reste un seul lien au clavier -->
          <RouterLink
            :to="{ name: 'sites', params: { siteId: row.site.id } }"
            class="font-medium after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-ring"
          >
            {{ row.site.id }}
          </RouterLink>
          <span class="ml-2 text-sm text-muted-foreground">{{
            SITE_TYPE_LABELS[row.site.type]
          }}</span>
        </p>
        <DataQualityBadge :qualite="row.qualite" />
      </div>
      <div class="flex items-center justify-between gap-3">
        <span
          class="text-sm font-semibold tabular-nums"
          :title="row.consommationKw === null ? noReading : undefined"
        >
          {{ formatKw(row.consommationKw) }}
          <span v-if="row.consommationKw === null" class="sr-only">{{ noReading }}</span>
        </span>
        <CapacityBar :pourcentage="pourcentage(row)" />
      </div>
      <p v-if="row.picPrevu" class="flex items-center gap-1 text-sm font-semibold">
        <TriangleAlert class="size-4" aria-hidden="true" />
        Pic prévu {{ formatRelativeHour(row.picPrevu.horodatage) }} ·
        {{ formatPct(row.picPrevu.pourcentageCapacite) }}
      </p>
    </li>
  </ul>

  <Table class="hidden sm:table">
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
        <TableCell
          class="tabular-nums"
          :title="row.consommationKw === null ? noReading : undefined"
        >
          {{ formatKw(row.consommationKw) }}
          <span v-if="row.consommationKw === null" class="sr-only">{{ noReading }}</span>
        </TableCell>
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
