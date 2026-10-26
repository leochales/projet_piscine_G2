<script setup lang="ts">
import { MapPinOff } from '@lucide/vue'
import { useRoute } from 'vue-router'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

const route = useRoute()
</script>

<template>
  <Card class="mx-auto max-w-lg">
    <CardContent class="flex flex-col items-center gap-3 py-6 text-center">
      <MapPinOff class="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 class="text-xl font-semibold">Page introuvable</h1>
      <p class="text-sm text-muted-foreground">
        L'adresse <code class="rounded bg-muted px-1 py-0.5 break-all">{{ route.fullPath }}</code>
        ne correspond à aucune page du dashboard. Le lien est peut-être ancien, ou mal recopié.
      </p>
      <div class="flex flex-wrap justify-center gap-2">
        <Button as-child>
          <RouterLink :to="{ name: 'overview' }">Vue d'ensemble</RouterLink>
        </Button>
        <Button variant="outline" as-child>
          <RouterLink :to="{ name: 'sites' }">Liste des sites</RouterLink>
        </Button>
      </div>
    </CardContent>
  </Card>
</template>
