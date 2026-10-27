<script setup lang="ts">
import { computed, ref } from 'vue'
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
import SortableHead from '@/components/overview/SortableHead.vue'
import DataQualityBadge from '@/components/overview/DataQualityBadge.vue'
import { formatKw, formatPct, formatRelativeDateTime, formatRelativeHour } from '@/lib/format'
import { capacityPct } from '@/lib/indicators'
import { siteTypeLabel } from '@/lib/labels'
import {
  DEFAULT_DIRECTION,
  nextSort,
  SITE_SORT_LABELS,
  sortSites,
  type SiteSort,
  type SiteSortKey,
} from '@/lib/sites'
import type { SiteOverview } from '@/types/energy'

const props = defineProps<{ rows: SiteOverview[] }>()
const emit = defineEmits<{ select: [siteId: string] }>()

// « — » sans mesure : la raison est donnée au survol et aux lecteurs d'écran
const noReading = 'Pas de mesure : capteur de consommation en panne'

const pourcentage = (row: SiteOverview) => capacityPct(row.consommationKw, row.site.capaciteKw)

// Tri : par site au départ. Un clic sur un en-tête trie la colonne, un 2e clic inverse le sens.
const sort = ref<SiteSort>({ key: 'site', direction: 'asc' })
const sorted = computed(() => sortSites(props.rows, sort.value.key, sort.value.direction))
const sortBy = (key: SiteSortKey) => (sort.value = nextSort(sort.value, key))

const directionOf = (key: SiteSortKey) => (sort.value.key === key ? sort.value.direction : null)

// Écran étroit : pas d'en-têtes, un menu de tri (chaque colonne dans son sens par défaut)
const sortKeys = Object.keys(SITE_SORT_LABELS) as SiteSortKey[]
function onMobileSort(event: Event) {
  const key = (event.target as HTMLSelectElement).value as SiteSortKey
  sort.value = { key, direction: DEFAULT_DIRECTION[key] }
}
</script>

<template>
  <!-- Écran étroit (sous 640 px) : une carte par site, les 6 colonnes ne tiendraient pas -->
  <div class="flex items-center justify-end gap-2 px-2 pt-2 text-sm sm:hidden">
    <label for="tri-sites" class="text-muted-foreground">Trier par</label>
    <select
      id="tri-sites"
      class="rounded-md border border-input bg-card px-2 py-1 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      :value="sort.key"
      @change="onMobileSort"
    >
      <option v-for="key in sortKeys" :key="key" :value="key">{{ SITE_SORT_LABELS[key] }}</option>
    </select>
  </div>
  <ul class="divide-y sm:hidden">
    <li v-for="row in sorted" :key="row.site.id" class="relative space-y-2 px-2 py-3">
      <div class="flex items-center justify-between gap-2">
        <p>
          <!-- after:inset-0 : le lien couvre toute la carte, qui reste un seul lien au clavier -->
          <RouterLink
            :to="{ name: 'sites', params: { siteId: row.site.id } }"
            class="font-medium after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-ring"
          >
            {{ row.site.id }}
          </RouterLink>
          <span class="ml-2 text-sm text-muted-foreground">{{ siteTypeLabel(row.site.type) }}</span>
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
          <span v-if="row.mesureLe" class="mt-0.5 block text-xs font-normal text-muted-foreground">
            {{ formatRelativeDateTime(row.mesureLe) }}
          </span>
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
        <SortableHead label="Site" :direction="directionOf('site')" @sort="sortBy('site')" />
        <TableHead>Type</TableHead>
        <SortableHead
          label="Consommation actuelle"
          :direction="directionOf('consommation')"
          @sort="sortBy('consommation')"
        />
        <SortableHead
          label="% de la capacité"
          :direction="directionOf('capacite')"
          @sort="sortBy('capacite')"
        />
        <TableHead>Pic prévu (48 h)</TableHead>
        <SortableHead
          label="Qualité des données"
          :direction="directionOf('qualite')"
          @sort="sortBy('qualite')"
        />
      </TableRow>
    </TableHeader>
    <TableBody>
      <!-- Toute la ligne est cliquable à la souris ; au clavier, c'est le lien de la 1re cellule -->
      <TableRow
        v-for="row in sorted"
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
        <TableCell>{{ siteTypeLabel(row.site.type) }}</TableCell>
        <TableCell
          class="tabular-nums"
          :title="row.consommationKw === null ? noReading : undefined"
        >
          {{ formatKw(row.consommationKw) }}
          <span v-if="row.consommationKw === null" class="sr-only">{{ noReading }}</span>
          <span v-if="row.mesureLe" class="mt-0.5 block text-xs font-normal text-muted-foreground">
            {{ formatRelativeDateTime(row.mesureLe) }}
          </span>
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
