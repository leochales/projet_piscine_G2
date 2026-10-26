<script setup lang="ts">
import type { Component } from 'vue'
import { storeToRefs } from 'pinia'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { logout } from '@/lib/auth'
import { useUserStore } from '@/stores/user'

// Page d'un compte connecté qui ne peut pas voir le dashboard (accès refusé, compte non
// rattaché) : le message, et de quoi se connecter avec un autre compte
defineProps<{ title: string; icon: Component }>()

const { email } = storeToRefs(useUserStore())
</script>

<template>
  <Card class="mx-auto max-w-lg">
    <CardContent class="flex flex-col items-center gap-3 py-6 text-center">
      <component :is="icon" class="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 class="text-xl font-semibold">{{ title }}</h1>
      <p class="text-sm text-muted-foreground">
        <slot :email="email" />
      </p>
      <Button variant="outline" @click="logout()">Se connecter avec un autre compte</Button>
    </CardContent>
  </Card>
</template>
