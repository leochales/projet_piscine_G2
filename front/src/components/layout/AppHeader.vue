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
import ThemeToggle from '@/components/layout/ThemeToggle.vue'
import { ROLE_LABELS, useUserStore, type Role } from '@/stores/user'

const { role, roleLabel } = storeToRefs(useUserStore())

const links = [
  { to: { name: 'overview' }, label: "Vue d'ensemble" },
  { to: { name: 'sites' }, label: 'Sites' },
  { to: { name: 'alerts' }, label: 'Alertes et recommandations' },
]

const roles = Object.entries(ROLE_LABELS) as [Role, string][]

// Changement de rôle réservé au développement (ou VITE_DEMO_ROLES=true) : en production,
// le rôle viendra de Keycloak et ne doit pas être modifiable.
const demoRoles = import.meta.env.DEV || import.meta.env.VITE_DEMO_ROLES === 'true'
</script>

<template>
  <header class="border-b border-border bg-card">
    <div
      class="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3 sm:px-6"
    >
      <RouterLink :to="{ name: 'overview' }" class="text-lg font-semibold">EnerVision</RouterLink>

      <nav class="flex flex-wrap gap-6 text-sm">
        <RouterLink
          v-for="link in links"
          :key="link.label"
          :to="link.to"
          class="border-b-2 border-transparent pb-1 text-muted-foreground hover:text-foreground"
          active-class="border-foreground! font-semibold text-foreground!"
        >
          {{ link.label }}
        </RouterLink>
      </nav>

      <div class="flex items-center gap-1">
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

        <ThemeToggle />
      </div>
    </div>
  </header>
</template>
