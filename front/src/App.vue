<script setup lang="ts">
import AppHeader from '@/components/layout/AppHeader.vue'
</script>

<template>
  <div class="min-h-screen">
    <AppHeader />
    <main class="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <RouterView />
    </main>
  </div>
</template>
