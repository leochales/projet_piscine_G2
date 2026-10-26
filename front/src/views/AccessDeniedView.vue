<script setup lang="ts">
import { ShieldOff } from '@lucide/vue'
import { storeToRefs } from 'pinia'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { logout } from '@/lib/auth'
import { useUserStore } from '@/stores/user'

const { email, roleLabel } = storeToRefs(useUserStore())
</script>

<template>
  <Card class="mx-auto max-w-lg">
    <CardContent class="flex flex-col items-center gap-3 py-6 text-center">
      <ShieldOff class="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 class="text-xl font-semibold">Accès refusé</h1>
      <p class="text-sm text-muted-foreground">
        Votre compte <span class="font-medium text-foreground">{{ email }}</span> ({{ roleLabel }})
        n'a pas accès à cette page. Si vous pensez que c'est une erreur, contactez le gestionnaire
        de votre entreprise.
      </p>
      <Button variant="outline" @click="logout()">Se connecter avec un autre compte</Button>
    </CardContent>
  </Card>
</template>
