<script setup lang="ts">
import { WifiOff, TriangleAlert } from '@lucide/vue'

import { describeSensors } from '@/lib/etat'
import { formatRelativeDateTime } from '@/lib/format'
import type { SiteStatus } from '@/types/energy'

// US4 : le site ne transmet plus, ou un de ses capteurs est en panne. Rien n'est affiché
// quand tout fonctionne. Si notre collecte est arrêtée, on le dit sans mettre le site en cause.
defineProps<{ status: SiteStatus }>()
</script>

<template>
  <div
    v-if="status.transmission === 'inconnu'"
    role="status"
    class="flex items-start gap-3 rounded-lg border border-warning bg-card p-4 text-sm"
  >
    <TriangleAlert class="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
    <p>
      <strong class="font-medium">La collecte des mesures est interrompue.</strong>
      Les chiffres de ce site ne sont plus mis à jour. Le site n'est pas en cause : la panne vient
      de la collecte EnerVision.
    </p>
  </div>

  <div
    v-else-if="status.transmission === 'muet'"
    role="status"
    class="flex items-start gap-3 rounded-lg border border-destructive bg-card p-4 text-sm"
  >
    <WifiOff class="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
    <p>
      <strong class="font-medium">Le site ne transmet plus.</strong>
      {{
        status.derniereMesureLe
          ? `Dernière mesure reçue ${formatRelativeDateTime(status.derniereMesureLe)} : les chiffres ne sont pas à jour.`
          : 'Aucune mesure reçue pour le moment.'
      }}
    </p>
  </div>

  <div
    v-if="status.capteursEnPanne.length"
    role="status"
    class="flex items-start gap-3 rounded-lg border border-warning bg-card p-4 text-sm"
  >
    <TriangleAlert class="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
    <p>
      <strong class="font-medium">
        {{ status.capteursEnPanne.length > 1 ? 'Capteurs en panne' : 'Capteur en panne' }} :
        {{ describeSensors(status.capteursEnPanne) }}.
      </strong>
      <template v-if="status.retablissementPrevu">
        Rétablissement prévu {{ formatRelativeDateTime(status.retablissementPrevu) }}.
      </template>
    </p>
  </div>
</template>
