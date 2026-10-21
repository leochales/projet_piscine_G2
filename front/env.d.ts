/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  /** "true" pour garder le sélecteur de rôle de démo dans un build de production */
  readonly VITE_DEMO_ROLES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
