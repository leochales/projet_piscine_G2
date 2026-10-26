<script setup lang="ts">
import { UserX } from '@lucide/vue'
import { storeToRefs } from 'pinia'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { logout } from '@/lib/auth'
import { useUserStore } from '@/stores/user'

const { email } = storeToRefs(useUserStore())
</script>

<template>
  <Card class="mx-auto max-w-lg">
    <CardContent class="flex flex-col items-center gap-3 py-6 text-center">
      <UserX class="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 class="text-xl font-semibold">Compte non rattaché</h1>
      <p class="text-sm text-muted-foreground">
        Votre compte <span class="font-medium text-foreground">{{ email }}</span> est bien connecté,
        mais il n'est rattaché à aucune entreprise dans EnerVision : aucune donnée ne peut
        s'afficher. Demandez au gestionnaire de votre entreprise de créer votre accès depuis le
        dashboard.
      </p>
      <Button variant="outline" @click="logout()">Se connecter avec un autre compte</Button>
    </CardContent>
  </Card>
</template>
