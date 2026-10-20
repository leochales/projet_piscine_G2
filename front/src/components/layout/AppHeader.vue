<script setup lang="ts">
import { storeToRefs } from 'pinia'

import { useUserStore } from '@/stores/user'

const { roleLabel } = storeToRefs(useUserStore())

const links = [
  { to: { name: 'overview' }, label: "Vue d'ensemble" },
  { to: { name: 'sites' }, label: 'Sites' },
  { to: { name: 'alerts' }, label: 'Alertes et recommandations' },
]
</script>

<template>
  <header class="border-b border-border bg-surface">
    <div
      class="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3 sm:px-6"
    >
      <RouterLink :to="{ name: 'overview' }" class="text-lg font-semibold">EnerVision</RouterLink>

      <nav class="flex gap-6 text-sm">
        <RouterLink
          v-for="link in links"
          :key="link.label"
          :to="link.to"
          class="border-b-2 border-transparent pb-1 text-muted hover:text-ink"
          active-class="border-ink! font-semibold text-ink!"
        >
          {{ link.label }}
        </RouterLink>
      </nav>

      <span class="text-sm text-muted">{{ roleLabel }}</span>
    </div>
  </header>
</template>
