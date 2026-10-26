<script setup lang="ts">
import { ShieldOff } from '@lucide/vue'
import { storeToRefs } from 'pinia'

import AccountNotice from '@/components/common/AccountNotice.vue'
import { useUserStore } from '@/stores/user'

const { roleLabel } = storeToRefs(useUserStore())
</script>

<template>
  <AccountNotice title="Accès refusé" :icon="ShieldOff">
    <template #default="{ email }">
      Votre compte <span class="font-medium text-foreground">{{ email }}</span> ({{ roleLabel }})
      n'a pas accès à cette page. Si vous pensez que c'est une erreur, contactez le gestionnaire de
      votre entreprise.
    </template>
  </AccountNotice>
</template>
