<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ChevronDown } from '@lucide/vue'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import DataFreshness from '@/components/common/DataFreshness.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import ConsumptionChart from '@/components/site/ConsumptionChart.vue'
import SiteAlerts from '@/components/site/SiteAlerts.vue'
import SiteRecommendations from '@/components/site/SiteRecommendations.vue'
import SiteTransmission from '@/components/site/SiteTransmission.vue'
import SitesTable from '@/components/overview/SitesTable.vue'
import { useActionsNotice } from '@/lib/actions'
import { formatEur, formatKw, formatRelativeHour, formatTonnes } from '@/lib/format'
import { SEUIL_ALERTE_PCT } from '@/lib/indicators'
import { predictedPeak } from '@/lib/predictions'
import { useAutoRefresh } from '@/lib/refresh'
import { useRequest } from '@/lib/request'
import {
  fetchOverview,
  fetchSiteCosts,
  fetchSiteOverview,
  fetchSiteSeries,
  fetchSiteStatuses,
  type SeriesRange,
} from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'

const props = defineProps<{ siteId?: string }>()
const router = useRouter()

const range = ref<SeriesRange>('24h')

// En type="single", recliquer sur le bouton actif le désélectionne : on garde alors le choix
function setRange(value: unknown) {
  if (value === '24h' || value === '7j') range.value = value
}

// Chaque appel est relancé quand le site (ou la période) change ; useRequest ignore la
// réponse d'un site quitté entre-temps. Sans identifiant (onglet « Sites »), on ne charge que
// la liste des sites, pour en choisir un.
// Liste des sites : choix d'un site (onglet « Sites ») et menu pour changer de site
const siteList = useRequest(fetchOverview)
const site = useRequest(async () => (props.siteId ? fetchSiteOverview(props.siteId) : undefined), {
  watch: () => props.siteId,
})
const costs = useRequest(async () => (props.siteId ? fetchSiteCosts(props.siteId) : undefined), {
  watch: () => props.siteId,
})
// La courbe garde l'identifiant de son site : on ne mélange jamais deux sites
const series = useRequest(
  async () => {
    const siteId = props.siteId
    return siteId ? { siteId, data: await fetchSiteSeries(siteId, range.value) } : undefined
  },
  { watch: [() => props.siteId, range] },
)

// Transmission et capteurs (US4) : la route renvoie tous les sites, on garde celui-ci.
// Inutile sans site (onglet « Sites »).
const statuses = useRequest(async () => (props.siteId ? fetchSiteStatuses() : undefined), {
  watch: () => props.siteId,
})
const siteStatus = computed(() =>
  statuses.data.value?.find((s) => s.siteId === current.value?.site.id),
)

// Recommandations de tous les sites (store partagé avec l'écran 3) : filtrées par site à
// l'affichage, inutile de les recharger quand on change de site
const operations = useOperationsStore()
const recommendations = useRequest(() => operations.reloadRecommendations())
// Alertes de tous les sites, de même : un dépassement de seuil apparaît au rafraîchissement
const alerts = useRequest(() => operations.reloadAlerts())
// Pourquoi les boutons d'action manquent sur les alertes et recommandations du site
const actionsNotice = useActionsNotice()

// Rafraîchit tout chaque minute ; un changement de site ou de période recharge déjà de
// lui-même (useRequest)
const freshness = useAutoRefresh([siteList, site, costs, series, statuses, alerts, recommendations])

const current = computed(() => site.data.value)
// Seuil du site, celui de l'ETL et du modèle : comparer à 90 % partout ferait annoncer un
// risque sur un data center (seuil 100 %) sans qu'aucune alerte ne soit jamais créée
const seuilPct = computed(() => current.value?.site.seuilAlertePct ?? SEUIL_ALERTE_PCT)
const notFound = computed(() => site.status.value === 'success' && !site.data.value)
const seriesIsEmpty = computed(() => series.data.value?.data.mesures.length === 0)

// Prévisions du site affiché (jamais celles du site quitté, encore en mémoire)
const predictions = computed(() => {
  const site = current.value?.site
  const loaded = series.data.value
  return site && loaded?.siteId === site.id ? loaded.data.predictions : null
})

// Pic de la prédiction : maximum de l'heure, sinon moyenne horaire
const peak = computed(() => (predictions.value ? predictedPeak(predictions.value) : null))

// Première heure où le modèle prévoit un pic au-dessus du seuil du site (pic_prevu). C'est
// sa décision, celle qui lève l'alerte de pic prévu : la page ne la recalcule pas, sinon les
// deux pourraient se contredire.
const firstAlert = computed(() => predictions.value?.find((p) => p.picPrevu) ?? null)

// Sans alerte du modèle, la borne haute du pic dit s'il reste une marge d'erreur à surveiller.
// Atteindre le seuil compte comme le dépasser (>=), comme dans le modèle et l'ETL.
const borneHauteAuSeuil = computed(() => {
  const site = current.value?.site
  if (!site || peak.value?.hauteKw == null) return null
  return peak.value.hauteKw >= (site.capaciteKw * seuilPct.value) / 100
})

// Mesures reçues mais aucune prévision : modèle pas encore passé, ou route en erreur
const noPrediction = computed(() => predictions.value?.length === 0 && !seriesIsEmpty.value)

const qualityText = computed(() => {
  const qualite = current.value?.qualite
  if (!qualite) return ''
  // data_quality décrit la dernière mesure, pas les 7 jours
  if (qualite.statut === 'bonne') return 'Dernière mesure de bonne qualité.'
  if (qualite.statut === 'partielle') {
    return qualite.heuresManquantes == null
      ? 'Dernière mesure incomplète.'
      : `${qualite.heuresManquantes} h de mesures manquantes : les valeurs ont été estimées.`
  }
  return 'Dernière mesure de mauvaise qualité.'
})

const openSite = (siteId: string) => router.push({ name: 'sites', params: { siteId } })
</script>

<template>
  <section v-if="!siteId" class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h1 class="text-xl font-semibold">Choisir un site</h1>
      <DataFreshness
        :updated-at="freshness.updatedAt.value"
        :refreshing="freshness.refreshing.value"
        :failed="freshness.failed.value"
        @refresh="freshness.refresh"
      />
    </div>
    <Card class="py-2">
      <CardContent class="px-2 sm:px-4">
        <RequestError
          v-if="siteList.status.value === 'error' && !siteList.data.value"
          what="les sites"
          @retry="siteList.reload"
        />
        <EmptyState
          v-else-if="siteList.data.value?.length === 0"
          title="Aucun site à afficher"
          description="Aucun site n'est rattaché à votre compte pour le moment."
        />
        <SitesTable
          v-else-if="siteList.data.value"
          :rows="siteList.data.value"
          @select="openSite"
        />
        <TableSkeleton v-else />
      </CardContent>
    </Card>
  </section>

  <RequestError
    v-else-if="site.status.value === 'error' && !current"
    :what="`le site ${siteId}`"
    @retry="site.reload"
  />

  <Card v-else-if="notFound">
    <CardContent>
      <EmptyState
        :title="`Site ${siteId} introuvable`"
        description="Il n'existe pas, ou n'est pas rattaché à votre compte."
      />
    </CardContent>
  </Card>

  <section v-else-if="current" class="space-y-4">
    <nav aria-label="Fil d'Ariane" class="text-sm text-muted-foreground">
      <ol class="flex items-center gap-1.5">
        <li>
          <RouterLink :to="{ name: 'sites' }" class="hover:text-foreground hover:underline">
            Sites
          </RouterLink>
        </li>
        <li aria-hidden="true">›</li>
        <li aria-current="page" class="text-foreground">{{ current.site.id }}</li>
      </ol>
    </nav>

    <div class="flex flex-wrap items-end justify-between gap-3">
      <h1 class="flex flex-wrap items-baseline gap-x-2 text-xl font-semibold">
        <!-- Le titre ouvre la liste des sites : on change de site sans revenir en arrière -->
        <DropdownMenu v-if="siteList.data.value?.length">
          <DropdownMenuTrigger
            class="-ml-1 inline-flex items-center gap-1 rounded-md px-1 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {{ current.site.id }} · {{ current.site.nom }}
            <ChevronDown class="size-4 text-muted-foreground" aria-hidden="true" />
            <span class="sr-only">(changer de site)</span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" class="max-h-80 overflow-y-auto">
            <DropdownMenuLabel>Changer de site</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup
              :model-value="current.site.id"
              @update:model-value="(value) => openSite(String(value))"
            >
              <DropdownMenuRadioItem
                v-for="row in siteList.data.value"
                :key="row.site.id"
                :value="row.site.id"
              >
                {{ row.site.id }} · {{ row.site.nom }}
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <span v-else>{{ current.site.id }} · {{ current.site.nom }}</span>
        <span class="text-sm font-normal text-muted-foreground">
          capacité {{ formatKw(current.site.capaciteKw) }}
        </span>
      </h1>
      <div class="flex flex-wrap items-center gap-3">
        <DataFreshness
          :updated-at="freshness.updatedAt.value"
          :refreshing="freshness.refreshing.value"
          :failed="freshness.failed.value"
          @refresh="freshness.refresh"
        />
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
    </div>

    <SiteTransmission v-if="siteStatus" :status="siteStatus" />

    <Card>
      <CardContent>
        <RequestError
          v-if="series.status.value === 'error' && !series.data.value"
          what="la courbe de consommation"
          @retry="series.reload"
        />
        <EmptyState
          v-else-if="seriesIsEmpty"
          title="Aucune mesure sur cette période"
          description="Le site n'a encore rien transmis. Les mesures apparaîtront dès leur réception."
        />
        <ConsumptionChart
          v-else-if="series.data.value"
          :series="series.data.value.data"
          :capacite-kw="current.site.capaciteKw"
          :seuil-pct="seuilPct"
        />
        <div v-else role="status" aria-live="polite">
          <span class="sr-only">Chargement de la courbe…</span>
          <Skeleton class="h-72 w-full" />
        </div>
        <p v-if="peak" class="mt-2 text-sm">
          Pic prévu {{ formatRelativeHour(peak.horodatage) }} :
          <strong>{{ formatKw(peak.kw) }}</strong>
          <template v-if="peak.basseKw !== null && peak.hauteKw !== null">
            ({{ formatKw(peak.basseKw) }} – {{ formatKw(peak.hauteKw) }})
          </template>
          <span v-if="peak.mesure === 'moyenne'" class="text-muted-foreground">
            · moyenne horaire</span
          >
        </p>
        <p v-else-if="noPrediction" class="mt-2 text-sm text-muted-foreground">
          Pas de prévision disponible pour le moment.
        </p>
      </CardContent>
    </Card>

    <div class="grid gap-4 md:grid-cols-3">
      <Card class="gap-2">
        <CardHeader><CardTitle>Ce que dit la fourchette</CardTitle></CardHeader>
        <CardContent class="text-sm text-muted-foreground">
          <template v-if="firstAlert">
            Le modèle prévoit un pic au-dessus de {{ seuilPct }} % de la capacité,
            {{ formatRelativeHour(firstAlert.horodatage) }} : risque de dépassement.
          </template>
          <template v-else-if="borneHauteAuSeuil">
            Le modèle ne prévoit pas de pic au-dessus de {{ seuilPct }} % de la capacité, mais la
            borne haute l'atteint : dépassement possible, à surveiller.
          </template>
          <template v-else-if="borneHauteAuSeuil === false">
            Même la borne haute du pic reste sous {{ seuilPct }} % de la capacité : pas de risque de
            dépassement.
          </template>
          <template v-else-if="peak">
            Le modèle ne prévoit pas de pic au-dessus de {{ seuilPct }} % de la capacité. Cette
            prévision n'a pas de fourchette : sa marge d'erreur n'est pas connue.
          </template>
          <template v-else-if="noPrediction">Pas de prévision disponible pour le moment.</template>
        </CardContent>
      </Card>
      <Card class="gap-2">
        <CardHeader><CardTitle>Qualité des données</CardTitle></CardHeader>
        <CardContent class="text-sm text-muted-foreground">{{ qualityText }}</CardContent>
      </Card>
      <Card class="gap-2">
        <CardHeader><CardTitle>Coût et CO₂ (7 jours)</CardTitle></CardHeader>
        <CardContent v-if="costs.data.value" class="text-sm text-muted-foreground">
          {{ formatEur(costs.data.value.coutEur) }} ·
          {{ formatTonnes(costs.data.value.co2Tonnes) }} CO₂
        </CardContent>
        <CardContent v-else-if="costs.status.value === 'error'" class="text-sm">
          <span class="text-muted-foreground">Indisponible.</span>
          <button type="button" class="ml-1 underline" @click="costs.reload">Réessayer</button>
        </CardContent>
        <CardContent v-else><Skeleton class="h-4 w-40" /></CardContent>
      </Card>
    </div>

    <p v-if="actionsNotice" class="text-sm text-muted-foreground">{{ actionsNotice }}</p>
    <SiteAlerts :site-id="current.site.id" :request="alerts" />
    <SiteRecommendations :site-id="current.site.id" :request="recommendations" />
  </section>

  <!-- Chargement du site : squelette de la page, à la place du titre et de la courbe -->
  <section v-else class="space-y-4" role="status" aria-live="polite">
    <span class="sr-only">Chargement du site…</span>
    <Skeleton class="h-7 w-72" />
    <Card>
      <CardContent><Skeleton class="h-72 w-full" /></CardContent>
    </Card>
  </section>
</template>
