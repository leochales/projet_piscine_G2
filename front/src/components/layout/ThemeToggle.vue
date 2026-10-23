<script setup lang="ts">
import { computed } from 'vue'
import { Moon, Sun } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'

const { isDark, toggleFrom } = useTheme()

// Le nom accessible annonce l'action, pas l'état
const label = computed(() => (isDark.value ? 'Passer en thème clair' : 'Passer en thème sombre'))

// Le cercle de la transition part du centre du bouton
function onClick(event: MouseEvent) {
  const { left, top, width, height } = (event.currentTarget as HTMLElement).getBoundingClientRect()
  void toggleFrom(left + width / 2, top + height / 2)
}
</script>

<template>
  <Button variant="ghost" size="icon" :aria-label="label" :title="label" @click="onClick">
    <!-- v-if : l'icône est recréée à chaque changement, ce qui rejoue son animation d'entrée
         (une animation et non une transition CSS, que useColorMode coupe pendant le changement) -->
    <Moon
      v-if="isDark"
      class="size-[1.15rem] animate-in duration-500 spin-in-90 zoom-in-50 motion-reduce:animate-none"
      aria-hidden="true"
    />
    <Sun
      v-else
      class="size-[1.15rem] animate-in duration-500 spin-in-90 zoom-in-50 motion-reduce:animate-none"
      aria-hidden="true"
    />
  </Button>
</template>
