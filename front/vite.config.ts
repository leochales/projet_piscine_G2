import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Le .env est partagé à la racine du dépôt
  const env = loadEnv(mode, '..', '')

  return {
    plugins: [vue(), tailwindcss(), vueDevTools()],
    envDir: '..',
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: 5173,
      // En dev, /api passe par Traefik comme en production : pas de CORS
      proxy: {
        '/api': `http://localhost:${env.HTTP_PORT || 80}`,
      },
    },
  }
})
