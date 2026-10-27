<script setup lang="ts">
import { computed } from 'vue'
import { TriangleAlert, WifiOff } from '@lucide/vue'

import { formatRelativeDateTime } from '@/lib/format'
import { transmissionSummary } from '@/lib/etat'
import type { SiteStatus } from '@/types/energy'

// US4 : les sites qui ne transmettent plus, pour savoir quels chiffres ne sont plus à jour.
// Rien n'est affiché quand tout transmet.
const props = defineProps<{ statuses: readonly SiteStatus[] }>()
defineEmits<{ select: [siteId: string] }>()

const summary = computed(() => transmissionSummary(props.statuses))

const lastSeen = (site: SiteStatus) =>
  site.derniereMesureLe
    ? `dernière mesure ${formatRelativeDateTime(site.derniereMesureLe)}`
    : 'aucune mesure reçue'
</script>

<template>
  <!-- Panne de notre côté : on ne met pas les sites en cause -->
  <div
    v-if="summary.collecteArretee"
    role="status"
    class="flex items-start gap-3 rounded-lg border border-warning bg-card p-4 text-sm"
  >
    <TriangleAlert class="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
    <p>
      <strong class="font-medium">La collecte des mesures est interrompue.</strong>
      Les chiffres affichés ne sont plus mis à jour. Les sites ne sont pas en cause : la panne vient
      de la collecte EnerVision.
    </p>
  </div>

  <div
    v-else-if="summary.sitesMuets.length"
    role="status"
    class="flex items-start gap-3 rounded-lg border border-destructive bg-card p-4 text-sm"
  >
    <WifiOff class="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
    <div class="space-y-1">
      <p class="font-medium">
        {{
          summary.sitesMuets.length > 1
            ? `${summary.sitesMuets.length} sites ne transmettent plus`
            : '1 site ne transmet plus'
        }}
        : leurs chiffres ne sont pas à jour.
      </p>
      <ul class="text-muted-foreground">
        <li v-for="site in summary.sitesMuets" :key="site.siteId">
          <button
            type="button"
            class="underline-offset-2 hover:text-foreground hover:underline"
            @click="$emit('select', site.siteId)"
          >
            {{ site.siteId }} · {{ site.nomSite }}
          </button>
          — {{ lastSeen(site) }}
        </li>
      </ul>
    </div>
  </div>
</template>
