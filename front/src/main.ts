import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { initAuth, onTokenRefresh } from './lib/auth'
import { useUserStore } from './stores/user'

async function start() {
  const claims = await initAuth()
  // Le routeur mémorise l'adresse à sa création : créé avant la connexion, il remettrait dans
  // l'adresse le #state=…&code=… que keycloak-js vient de retirer
  const { default: router } = await import('./router')

  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)

  const user = useUserStore(pinia)
  user.setFromToken(claims)
  onTokenRefresh((refreshed) => user.setFromToken(refreshed))

  app.use(router)
  app.mount('#app')
}

start().catch((error: unknown) => {
  console.error(error)
  const root = document.getElementById('app')
  if (root) {
    root.textContent = 'Le service de connexion est indisponible. Réessayez dans quelques instants.'
  }
})
