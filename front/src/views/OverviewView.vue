<script setup lang="ts">
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import DataFreshness from '@/components/common/DataFreshness.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import KpiCard from '@/components/overview/KpiCard.vue'
import SitesTable from '@/components/overview/SitesTable.vue'
import { formatEur, formatKw, formatSignedPct, formatTonnes } from '@/lib/format'
import { trend } from '@/lib/indicators'
import { useAutoRefresh } from '@/lib/refresh'
import { useRequest } from '@/lib/request'
import { fetchKpis, fetchOverview } from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'

const router = useRouter()

// Alertes et économies viennent du store partagé : elles suivent les actions de l'écran 3
const operations = useOperationsStore()
const { pendingAlerts, pendingCritical, savings } = storeToRefs(operations)

// Les KPI combinent les indicateurs du parc et le store : ils attendent les deux
const kpis = useRequest(async () => (await Promise.all([fetchKpis(), operations.load()]))[0])
const sites = useRequest(fetchOverview)
// Alertes et économies ne sont pas rafraîchies : le store garderait sinon les actions faites
// à l'écran 3 seulement jusqu'au rafraîchissement suivant (pas encore d'API pour les enregistrer)
const freshness = useAutoRefresh([kpis, sites])

const sitesWithoutReading = (n: number) => (n > 1 ? `${n} sites sans mesure` : '1 site sans mesure')

const openSite = (siteId: string) => router.push({ name: 'sites', params: { siteId } })
</script>

<template>
  <section class="space-y-6">
    <div class="flex min-h-6 items-center justify-between gap-4">
      <h1 class="sr-only">Vue d'ensemble du parc</h1>
      <DataFreshness
        class="ml-auto"
        :updated-at="freshness.updatedAt.value"
        :refreshing="freshness.refreshing.value"
        :failed="freshness.failed.value"
        @refresh="freshness.refresh"
      />
    </div>

    <Card v-if="kpis.status.value === 'error' && !kpis.data.value" class="py-2">
      <CardContent class="px-2 sm:px-4">
        <RequestError what="les indicateurs du parc" @retry="kpis.reload" />
      </CardContent>
    </Card>
    <div v-else-if="kpis.data.value" class="grid grid-cols-2 gap-4 lg:grid-cols-5">
      <!-- Un site sans mesure est exclu du total : on le dit, sinon le total paraît complet -->
      <KpiCard
        label="Consommation actuelle"
        :value="formatKw(kpis.data.value.consommationKw)"
        :hint="
          kpis.data.value.nbSitesSansMesure > 0
            ? `Données incomplètes : ${sitesWithoutReading(kpis.data.value.nbSitesSansMesure)}`
            : `${kpis.data.value.nbSites} sites`
        "
        :warning="kpis.data.value.nbSitesSansMesure > 0"
      />
      <KpiCard
        label="Coût aujourd'hui"
        :value="formatEur(kpis.data.value.coutJourEur)"
        :hint="`${formatSignedPct(kpis.data.value.variationCoutPct)} vs hier`"
        :trend="trend(kpis.data.value.variationCoutPct, 'baisse')"
      />
      <KpiCard
        label="CO₂ aujourd'hui"
        :value="formatTonnes(kpis.data.value.co2JourTonnes)"
        hint="facteurs ADEME"
      />
      <KpiCard
        label="Alertes actives"
        :value="String(pendingAlerts.length)"
        :hint="`dont ${pendingCritical} critique${pendingCritical > 1 ? 's' : ''}`"
      />
      <!-- Sur 2 colonnes, la 5e carte prend toute la largeur au lieu de laisser un trou -->
      <KpiCard
        class="col-span-2 lg:col-span-1"
        label="Économies réalisées"
        :value="formatEur(savings)"
        hint="ce mois-ci"
      />
    </div>
    <!-- Squelettes à la taille des cartes : pas de saut de mise en page à l'arrivée -->
    <div v-else class="grid grid-cols-2 gap-4 lg:grid-cols-5" role="status" aria-live="polite">
      <span class="sr-only">Chargement des indicateurs…</span>
      <Card v-for="n in 5" :key="n" :class="['gap-1 py-4', n === 5 && 'col-span-2 lg:col-span-1']">
        <CardContent class="space-y-2 px-4">
          <Skeleton class="h-3 w-24" />
          <Skeleton class="h-8 w-28" />
          <Skeleton class="h-4 w-16" />
        </CardContent>
      </Card>
    </div>

    <Card class="py-2">
      <CardContent class="px-2 sm:px-4">
        <RequestError
          v-if="sites.status.value === 'error' && !sites.data.value"
          what="les sites"
          @retry="sites.reload"
        />
        <EmptyState
          v-else-if="sites.data.value?.length === 0"
          title="Aucun site à afficher"
          description="Aucun site n'est rattaché à votre compte pour le moment."
        />
        <SitesTable v-else-if="sites.data.value" :rows="sites.data.value" @select="openSite" />
        <TableSkeleton v-else />
      </CardContent>
    </Card>
  </section>
</template>
