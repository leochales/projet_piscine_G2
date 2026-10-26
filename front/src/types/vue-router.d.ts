import 'vue-router'

import type { Role } from '@/stores/user'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    /** Rôles autorisés ; sans cette clé, la page est accessible à tout utilisateur connecté */
    roles?: readonly Role[]
  }
}
