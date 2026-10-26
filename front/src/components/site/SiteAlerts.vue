<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import AlertsTable from '@/components/alerts/AlertsTable.vue'
import { useAcknowledgeAlert, useCanAcknowledge } from '@/lib/actions'
import type { RequestState } from '@/lib/request'
import { useOperationsStore } from '@/stores/operations'

// US3 : les alertes en cours du site, dont les dépassements de seuil, visibles par tous ceux
// qui consultent ce site. Le chargement appartient à la page du site, qui le rafraîchit
// avec le reste (useAutoRefresh) : un nouveau dépassement apparaît sans recharger la page.
const props = defineProps<{
  siteId: string
  request: Pick<RequestState<unknown>, 'status' | 'updatedAt' | 'reload'>
}>()

// Même store que l'écran 3 et l'en-tête : une prise en compte faite ici s'y voit aussitôt
const { alerts, pending } = storeToRefs(useOperationsStore())
const siteAlerts = computed(() => alerts.value.filter((a) => a.siteId === props.siteId))

const acknowledge = useAcknowledgeAlert()
const canAcknowledge = useCanAcknowledge()

// Squelette au premier chargement seulement : un rafraîchissement garde la liste affichée
const firstLoad = computed(() => !props.request.updatedAt.value)
</script>

<template>
  <Card>
    <CardHeader><CardTitle>Alertes en cours</CardTitle></CardHeader>
    <CardContent>
      <RequestError
        v-if="firstLoad && request.status.value === 'error'"
        what="les alertes"
        @retry="request.reload"
      />
      <TableSkeleton v-else-if="firstLoad" :rows="2" />
      <EmptyState
        v-else-if="siteAlerts.length === 0"
        title="Aucune alerte en cours"
        description="Le site n'a dépassé aucun seuil et ne signale aucune anomalie."
      />
      <AlertsTable
        v-else
        :alerts="siteAlerts"
        :can-act-on="canAcknowledge"
        :pending="pending"
        @acknowledge="acknowledge"
      />
    </CardContent>
  </Card>
</template>
