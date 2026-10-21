<script setup lang="ts">
import { computed, onWatcherCleanup, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import ConsumptionChart from '@/components/site/ConsumptionChart.vue'
import SitesTable from '@/components/overview/SitesTable.vue'
import { formatEur, formatKw, formatRelativeHour, formatTonnes } from '@/lib/format'
import {
  fetchOverview,
  fetchSiteCosts,
  fetchSiteOverview,
  fetchSiteSeries,
  type SeriesRange,
} from '@/services/dashboard'
import type { SiteOverview, SiteSeries } from '@/types/energy'

const props = defineProps<{ siteId?: string }>()
const router = useRouter()

const SEUIL_PCT = 90

const range = ref<SeriesRange>('24h')
const current = ref<SiteOverview>()
// La courbe garde l'identifiant de son site : on ne mélange jamais deux sites
const series = ref<{ siteId: string; data: SiteSeries }>()
const costs = ref<{ coutEur: number; co2Tonnes: number }>()
const allSites = ref<SiteOverview[]>([])
const notFound = ref(false)

// En type="single", recliquer sur le bouton actif le désélectionne : on garde alors le choix
function setRange(value: unknown) {
  if (value === '24h' || value === '7j') range.value = value
}

/** Drapeau « annulé » levé quand le watcher est relancé (changement de site ou de période) */
function useCancelled() {
  let cancelled = false
  onWatcherCleanup(() => (cancelled = true))
  return () => cancelled
}

// Sans identifiant (onglet « Sites »), on affiche la liste pour choisir un site
watch(
  () => props.siteId,
  async (siteId) => {
    const isCancelled = useCancelled()
    notFound.value = false
    current.value = undefined
    costs.value = undefined

    if (!siteId) {
      const sites = await fetchOverview()
      if (!isCancelled()) allSites.value = sites
      return
    }

    const site = await fetchSiteOverview(siteId)
    if (isCancelled()) return
    if (!site) {
      notFound.value = true
      return
    }
    current.value = site

    const siteCosts = await fetchSiteCosts(siteId)
    if (!isCancelled()) costs.value = siteCosts
  },
  { immediate: true },
)

watch(
  [() => props.siteId, range],
  async ([siteId, r]) => {
    const isCancelled = useCancelled()
    series.value = undefined
    if (!siteId) return
    const data = await fetchSiteSeries(siteId, r)
    if (!isCancelled()) series.value = { siteId, data }
  },
  { immediate: true },
)

// Pic de la prédiction et position de sa borne haute par rapport au seuil
const peak = computed(() => {
  const site = current.value?.site
  const predictions = series.value?.data.predictions
  if (!site || !predictions?.length || series.value?.siteId !== site.id) return null
  const top = predictions.reduce((a, b) => (b.kw > a.kw ? b : a))
  const seuilKw = (site.capaciteKw * SEUIL_PCT) / 100
  return { ...top, depasseSeuil: top.hauteKw > seuilKw }
})

const qualityText = computed(() => {
  const qualite = current.value?.qualite
  if (!qualite) return ''
  if (qualite.statut === 'bonne') return 'Aucune mesure manquante sur 7 jours.'
  if (qualite.statut === 'partielle')
    return `${qualite.heuresManquantes} h de mesures manquantes : les valeurs ont été estimées.`
  return 'Données insuffisantes : la prédiction est peu fiable.'
})

const openSite = (siteId: string) => router.push({ name: 'sites', params: { siteId } })
</script>

<template>
  <section v-if="!siteId" class="space-y-4">
    <h1 class="text-xl font-semibold">Choisir un site</h1>
    <Card class="py-2">
      <CardContent class="px-2 sm:px-4">
        <SitesTable :rows="allSites" @select="openSite" />
      </CardContent>
    </Card>
  </section>

  <p v-else-if="notFound" class="text-muted-foreground">Site {{ siteId }} introuvable.</p>

  <section v-else-if="current" class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <h1 class="text-xl font-semibold">
        {{ current.site.id }} · {{ current.site.nom }}
        <span class="ml-1 text-sm font-normal text-muted-foreground">
          capacité {{ formatKw(current.site.capaciteKw) }}
        </span>
      </h1>
      <ToggleGroup
        :model-value="range"
        type="single"
        @update:model-value="setRange"
        variant="outline"
        aria-label="Période affichée"
      >
        <ToggleGroupItem
          value="24h"
          class="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >24 heures</ToggleGroupItem
        >
        <ToggleGroupItem
          value="7j"
          class="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >7 jours</ToggleGroupItem
        >
      </ToggleGroup>
    </div>

    <Card>
      <CardContent>
        <ConsumptionChart
          v-if="series"
          :series="series.data"
          :capacite-kw="current.site.capaciteKw"
          :seuil-pct="SEUIL_PCT"
        />
        <p v-else class="h-72 text-muted-foreground">Chargement de la courbe…</p>
        <p v-if="peak" class="mt-2 text-sm">
          Pic prévu {{ formatRelativeHour(peak.horodatage) }} :
          <strong>{{ formatKw(peak.kw) }}</strong>
          ({{ formatKw(peak.basseKw) }} – {{ formatKw(peak.hauteKw) }})
        </p>
      </CardContent>
    </Card>

    <div class="grid gap-4 md:grid-cols-3">
      <Card class="gap-2">
        <CardHeader><CardTitle>Ce que dit la fourchette</CardTitle></CardHeader>
        <CardContent class="text-sm text-muted-foreground">
          <template v-if="peak?.depasseSeuil">
            La borne haute du pic dépasse {{ SEUIL_PCT }} % de la capacité : risque réel de
            dépassement, une recommandation est proposée.
          </template>
          <template v-else-if="peak">
            Même la borne haute du pic reste sous {{ SEUIL_PCT }} % de la capacité : pas de risque
            de dépassement.
          </template>
        </CardContent>
      </Card>
      <Card class="gap-2">
        <CardHeader><CardTitle>Qualité des données</CardTitle></CardHeader>
        <CardContent class="text-sm text-muted-foreground">{{ qualityText }}</CardContent>
      </Card>
      <Card class="gap-2">
        <CardHeader><CardTitle>Coût et CO₂ (7 jours)</CardTitle></CardHeader>
        <CardContent v-if="costs" class="text-sm text-muted-foreground">
          {{ formatEur(costs.coutEur) }} · {{ formatTonnes(costs.co2Tonnes) }} CO₂
        </CardContent>
      </Card>
    </div>
  </section>
</template>
