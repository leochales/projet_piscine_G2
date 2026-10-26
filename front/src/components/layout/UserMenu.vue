<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { ChevronDown, LogOut } from '@lucide/vue'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { logout } from '@/lib/auth'
import { useUserStore } from '@/stores/user'

const { nom, email, roleLabel } = storeToRefs(useUserStore())
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button variant="ghost" size="sm" class="text-muted-foreground">
        {{ nom }}
        <ChevronDown aria-hidden="true" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      <DropdownMenuLabel class="flex flex-col gap-0.5">
        <span>{{ email }}</span>
        <span class="text-xs font-normal text-muted-foreground">{{ roleLabel }}</span>
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem @select="logout()">
        <LogOut aria-hidden="true" />
        Se déconnecter
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
