<script setup lang="ts">
import { ref } from 'vue'
import { Check, LoaderCircle } from '@lucide/vue'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import SeverityBadge from '@/components/alerts/SeverityBadge.vue'
import type { Alert } from '@/types/energy'

const props = defineProps<{
  alerts: Alert[]
  canActOn: (siteId: string) => boolean
  /** Alertes dont la prise en compte est en cours d'envoi */
  pending?: ReadonlySet<string>
}>()
const emit = defineEmits<{ acknowledge: [alertId: string] }>()

// La prise en compte est définitive (une deuxième est refusée, US7) : on la fait confirmer.
// L'alerte choisie est gardée à part de l'ouverture : la boîte se ferme avant l'appel de
// confirm(), et son texte doit rester affiché pendant l'animation de fermeture.
const dialogOpen = ref(false)
const toConfirm = ref<Alert>()

function askConfirmation(alert: Alert) {
  toConfirm.value = alert
  dialogOpen.value = true
}

function confirm() {
  if (toConfirm.value) emit('acknowledge', toConfirm.value.id)
  dialogOpen.value = false
}

const isPending = (alert: Alert) => props.pending?.has(alert.id) ?? false
</script>

<template>
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Gravité</TableHead>
        <TableHead>Site</TableHead>
        <TableHead>Alerte</TableHead>
        <TableHead><span class="sr-only">Action</span></TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      <TableRow v-for="alert in alerts" :key="alert.id">
        <TableCell><SeverityBadge :gravite="alert.gravite" /></TableCell>
        <TableCell>{{ alert.siteId }}</TableCell>
        <TableCell class="whitespace-normal">{{ alert.message }}</TableCell>
        <TableCell class="text-right">
          <span
            v-if="alert.priseEnCompte"
            class="inline-flex items-center gap-1 text-sm text-muted-foreground"
          >
            <Check class="size-4" aria-hidden="true" /> Prise en compte
          </span>
          <Button
            v-else-if="canActOn(alert.siteId)"
            variant="outline"
            size="sm"
            :disabled="isPending(alert)"
            @click="askConfirmation(alert)"
          >
            <LoaderCircle
              v-if="isPending(alert)"
              class="animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
            Prise en compte
          </Button>
        </TableCell>
      </TableRow>
      <TableEmpty v-if="alerts.length === 0" :colspan="4">Aucune alerte active</TableEmpty>
    </TableBody>
  </Table>

  <AlertDialog v-model:open="dialogOpen">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>Prendre en compte cette alerte ?</AlertDialogTitle>
        <AlertDialogDescription>
          <span class="block font-medium text-foreground">
            {{ toConfirm?.siteId }} · {{ toConfirm?.message }}
          </span>
          Elle sera marquée comme prise en compte pour toutes les personnes qui suivent ce site.
          Cette action est définitive.
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>Annuler</AlertDialogCancel>
        <AlertDialogAction @click="confirm">Confirmer la prise en compte</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
