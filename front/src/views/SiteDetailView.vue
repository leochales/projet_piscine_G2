<script setup lang="ts">
defineProps<{ siteId?: string }>()
</script>

<template>
  <section>
    <h1 class="text-xl font-semibold">{{ siteId ?? 'Sites' }}</h1>
    <p class="mt-2 text-muted">Historique et prédiction de consommation (EF-05, EF-08 à EF-10).</p>
  </section>
</template>
