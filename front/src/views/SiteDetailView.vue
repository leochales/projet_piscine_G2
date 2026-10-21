<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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

const range = ref<SeriesRange>('48h')
const current = ref<SiteOverview>()
const series = ref<SiteSeries>()
const costs = ref<{ coutEur: number; co2Tonnes: number }>()
const allSites = ref<SiteOverview[]>([])
const notFound = ref(false)

// Sans identifiant (onglet « Sites »), on affiche la liste pour choisir un site
watch(
  () => props.siteId,
  async (siteId) => {
    notFound.value = false
    series.value = undefined
    if (!siteId) {
      allSites.value = await fetchOverview()
      return
    }
    current.value = await fetchSiteOverview(siteId)
    if (!current.value) {
      notFound.value = true
      return
    }
    costs.value = await fetchSiteCosts(siteId)
  },
  { immediate: true },
)

watch(
  [() => props.siteId, range],
  async ([siteId, r]) => {
    if (siteId) series.value = await fetchSiteSeries(siteId, r)
  },
  { immediate: true },
)

// Pic de la prédiction et position de sa borne haute par rapport au seuil
const peak = computed(() => {
  if (!series.value || !current.value) return null
  const top = series.value.predictions.reduce((a, b) => (b.kw > a.kw ? b : a))
  const seuilKw = (current.value.site.capaciteKw * SEUIL_PCT) / 100
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
      <ToggleGroup v-model="range" type="single" variant="outline" aria-label="Période affichée">
        <ToggleGroupItem
          value="48h"
          class="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >48 heures</ToggleGroupItem
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
          :series="series"
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
