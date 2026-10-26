/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  /** Adresse de Keycloak, /auth par défaut (même origine que le front derrière Traefik) */
  readonly VITE_KEYCLOAK_URL?: string
  /** Realm Keycloak, enervision par défaut */
  readonly VITE_KEYCLOAK_REALM?: string
  /** Client Keycloak du front, enervision-front par défaut */
  readonly VITE_KEYCLOAK_CLIENT_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
