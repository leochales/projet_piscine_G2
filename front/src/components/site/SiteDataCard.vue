<script setup lang="ts">
import { computed } from 'vue'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import EmptyState from '@/components/common/EmptyState.vue'
import RequestError from '@/components/common/RequestError.vue'
import type { RequestState } from '@/lib/request'

// Carte d'une liste de la page d'un site (alertes, recommandations) : chargement, erreur,
// état vide et liste. Le chargement appartient à la page, qui le rafraîchit avec le reste
// (useAutoRefresh).
const props = defineProps<{
  title: string
  /** Ce qui n'a pas pu être chargé : « les alertes »… */
  what: string
  request: Pick<RequestState<unknown>, 'status' | 'updatedAt' | 'reload'>
  empty: boolean
  emptyTitle: string
  emptyDescription: string
}>()

// Squelette et erreur au premier chargement seulement : un rafraîchissement garde la liste
// affichée
const firstLoad = computed(() => !props.request.updatedAt.value)
</script>

<template>
  <Card>
    <CardHeader
      ><CardTitle>{{ title }}</CardTitle></CardHeader
    >
    <CardContent>
      <RequestError
        v-if="firstLoad && request.status.value === 'error'"
        :what="what"
        @retry="request.reload"
      />
      <div v-else-if="firstLoad" role="status" aria-live="polite">
        <span class="sr-only">Chargement de {{ what }}…</span>
        <slot name="loading" />
      </div>
      <EmptyState v-else-if="empty" :title="emptyTitle" :description="emptyDescription" />
      <slot v-else />
    </CardContent>
  </Card>
</template>
