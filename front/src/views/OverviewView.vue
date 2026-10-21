<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import { Card, CardContent } from '@/components/ui/card'
import KpiCard from '@/components/overview/KpiCard.vue'
import SitesTable from '@/components/overview/SitesTable.vue'
import { formatEur, formatKw, formatSignedPct, formatTonnes } from '@/lib/format'
import { fetchKpis, fetchOverview } from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'
import type { FleetKpis, SiteOverview } from '@/types/energy'

const router = useRouter()
const kpis = ref<FleetKpis>()
const rows = ref<SiteOverview[]>([])

// Alertes et économies viennent du store partagé : elles suivent les actions de l'écran 3
const operations = useOperationsStore()
const { pendingAlerts, pendingCritical, savings } = storeToRefs(operations)

onMounted(async () => {
  ;[kpis.value, rows.value] = await Promise.all([fetchKpis(), fetchOverview(), operations.load()])
})

const openSite = (siteId: string) => router.push({ name: 'sites', params: { siteId } })
</script>

<template>
  <section class="space-y-6">
    <h1 class="sr-only">Vue d'ensemble du parc</h1>

    <div v-if="kpis" class="grid grid-cols-2 gap-4 lg:grid-cols-5">
      <KpiCard
        label="Consommation actuelle"
        :value="formatKw(kpis.consommationKw)"
        :hint="`${kpis.nbSites} sites`"
      />
      <KpiCard
        label="Coût aujourd'hui"
        :value="formatEur(kpis.coutJourEur)"
        :hint="`${formatSignedPct(kpis.variationCoutPct)} vs hier`"
      />
      <KpiCard
        label="CO₂ aujourd'hui"
        :value="formatTonnes(kpis.co2JourTonnes)"
        hint="facteurs ADEME"
      />
      <KpiCard
        label="Alertes actives"
        :value="String(pendingAlerts.length)"
        :hint="`dont ${pendingCritical} critique${pendingCritical > 1 ? 's' : ''}`"
      />
      <KpiCard label="Économies réalisées" :value="formatEur(savings)" hint="ce mois-ci" />
    </div>

    <Card class="py-2">
      <CardContent class="px-2 sm:px-4">
        <p v-if="rows.length === 0" class="p-4 text-muted-foreground">Chargement des sites…</p>
        <SitesTable v-else :rows="rows" @select="openSite" />
      </CardContent>
    </Card>
  </section>
</template>
