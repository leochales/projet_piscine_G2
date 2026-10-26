<script setup lang="ts">
import { UserX } from '@lucide/vue'

import AccountNotice from '@/components/common/AccountNotice.vue'
</script>

<template>
  <AccountNotice title="Compte non rattaché" :icon="UserX">
    <template #default="{ email }">
      Votre compte <span class="font-medium text-foreground">{{ email }}</span> est bien connecté,
      mais il n'est rattaché à aucune entreprise dans EnerVision : aucune donnée ne peut s'afficher.
      Demandez au gestionnaire de votre entreprise de créer votre accès depuis le dashboard.
    </template>
  </AccountNotice>
</template>
