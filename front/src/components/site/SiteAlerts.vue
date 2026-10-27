<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import TableSkeleton from '@/components/common/TableSkeleton.vue'
import AlertsTable from '@/components/alerts/AlertsTable.vue'
import SiteDataCard from '@/components/site/SiteDataCard.vue'
import { useAcknowledgeAlert, useCanAcknowledge } from '@/lib/actions'
import type { RequestState } from '@/lib/request'
import { useOperationsStore } from '@/stores/operations'

// US3 : les alertes en cours du site, dont les dépassements de seuil, visibles par tous ceux
// qui consultent ce site. Rafraîchies avec la page : un nouveau dépassement apparaît sans
// recharger.
const props = defineProps<{
  siteId: string
  request: Pick<RequestState<unknown>, 'status' | 'updatedAt' | 'reload'>
}>()

// Même store que l'écran 3 et l'en-tête : une prise en compte faite ici s'y voit aussitôt
const { alerts, pending } = storeToRefs(useOperationsStore())
const siteAlerts = computed(() => alerts.value.filter((a) => a.siteId === props.siteId))

const acknowledge = useAcknowledgeAlert()
const canAcknowledge = useCanAcknowledge()
</script>

<template>
  <SiteDataCard
    title="Alertes en cours"
    what="les alertes"
    :request="request"
    :empty="siteAlerts.length === 0"
    empty-title="Aucune alerte en cours"
    empty-description="Le site n'a dépassé aucun seuil et ne signale aucune anomalie."
  >
    <template #loading><TableSkeleton :rows="2" /></template>
    <AlertsTable
      :alerts="siteAlerts"
      :can-act-on="canAcknowledge"
      :pending="pending"
      @acknowledge="acknowledge"
    />
  </SiteDataCard>
</template>
