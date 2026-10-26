<script setup lang="ts">
import 'vue-sonner/style.css'

import AppHeader from '@/components/layout/AppHeader.vue'
import { Toaster } from '@/components/ui/sonner'
import { useTheme } from '@/lib/theme'

const { isDark } = useTheme()
</script>

<template>
  <div class="min-h-screen">
    <AppHeader />
    <main class="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <RouterView />
    </main>
    <!-- Messages après une action (Accepter, Refuser, Prise en compte), aux couleurs du thème -->
    <Toaster :theme="isDark ? 'dark' : 'light'" position="bottom-right" close-button />
  </div>
</template>
