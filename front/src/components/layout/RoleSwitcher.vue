<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { ChevronDown } from '@lucide/vue'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { ROLE_LABELS, useUserStore, type Role } from '@/stores/user'

const { role, roleLabel } = storeToRefs(useUserStore())

const roles = Object.entries(ROLE_LABELS) as [Role, string][]

// Changement de rôle réservé au développement (ou VITE_DEMO_ROLES=true) : en production,
// le rôle viendra de Keycloak et ne doit pas être modifiable.
const demoRoles = import.meta.env.DEV || import.meta.env.VITE_DEMO_ROLES === 'true'
</script>

<template>
  <!-- Choix du rôle : démonstration en attendant Keycloak -->
  <DropdownMenu v-if="demoRoles">
    <DropdownMenuTrigger as-child>
      <Button variant="ghost" size="sm" class="text-muted-foreground">
        {{ roleLabel }}
        <ChevronDown />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      <DropdownMenuLabel>Rôle (démo)</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuRadioGroup v-model="role">
        <DropdownMenuRadioItem v-for="[value, label] in roles" :key="value" :value="value">
          {{ label }}
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
  <span v-else class="px-2 text-sm text-muted-foreground">{{ roleLabel }}</span>
</template>
