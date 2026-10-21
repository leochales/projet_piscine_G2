import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config.ts'

// vite.config.ts est une fonction (il lit le .env) : on l'appelle avant de fusionner
export default defineConfig((configEnv) =>
  mergeConfig(
    viteConfig(configEnv),
    defineConfig({
      test: {
        environment: 'jsdom',
        exclude: [...configDefaults.exclude, 'e2e/**'],
        root: fileURLToPath(new URL('./', import.meta.url)),
        // Couverture mesurée sur la logique métier, pas sur les composants d'affichage
        coverage: {
          provider: 'v8',
          include: ['src/stores/**', 'src/lib/**', 'src/services/**'],
          // json-summary : lu par la CI pour le résumé ; html : rapport détaillé téléchargeable
          reporter: ['text-summary', 'text', 'json-summary', 'html'],
          thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
        },
      },
    }),
  ),
)
