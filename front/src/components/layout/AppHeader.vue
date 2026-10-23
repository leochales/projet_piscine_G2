<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { onKeyStroke } from '@vueuse/core'
import { Menu, X } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import RoleSwitcher from '@/components/layout/RoleSwitcher.vue'
import ThemeToggle from '@/components/layout/ThemeToggle.vue'

const links = [
  { to: { name: 'overview' }, label: "Vue d'ensemble" },
  { to: { name: 'sites' }, label: 'Sites' },
  { to: { name: 'alerts' }, label: 'Alertes et recommandations' },
]

// Menu mobile (sous 768 px) : fermé dès qu'on change de page, ou avec Échap
const menuOpen = ref(false)
const route = useRoute()
watch(
  () => route.fullPath,
  () => (menuOpen.value = false),
)
onKeyStroke('Escape', () => (menuOpen.value = false))
</script>

<template>
  <header class="border-b border-border bg-card">
    <div class="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
      <RouterLink :to="{ name: 'overview' }" class="text-lg font-semibold">EnerVision</RouterLink>

      <nav aria-label="Navigation principale" class="hidden gap-6 text-sm md:flex">
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
        <div class="hidden md:block"><RoleSwitcher /></div>
        <ThemeToggle />
        <Button
          variant="ghost"
          size="icon"
          class="md:hidden"
          :aria-label="menuOpen ? 'Fermer le menu' : 'Ouvrir le menu'"
          :aria-expanded="menuOpen"
          aria-controls="menu-mobile"
          @click="menuOpen = !menuOpen"
        >
          <X v-if="menuOpen" aria-hidden="true" />
          <Menu v-else aria-hidden="true" />
        </Button>
      </div>
    </div>

    <!-- Menu mobile : se déroule sous l'en-tête, sans recouvrir la page -->
    <div
      v-show="menuOpen"
      id="menu-mobile"
      class="border-t border-border px-4 pt-2 pb-3 animate-in fade-in slide-in-from-top-1 motion-reduce:animate-none md:hidden"
    >
      <nav aria-label="Navigation principale" class="flex flex-col">
        <RouterLink
          v-for="link in links"
          :key="link.label"
          :to="link.to"
          class="rounded-md px-2 py-2.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          active-class="bg-accent font-semibold text-foreground!"
        >
          {{ link.label }}
        </RouterLink>
      </nav>
      <div class="mt-2 flex items-center justify-between border-t border-border pt-2">
        <span class="px-2 text-xs text-muted-foreground">Rôle</span>
        <RoleSwitcher />
      </div>
    </div>
  </header>
</template>
