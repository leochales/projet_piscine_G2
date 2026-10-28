import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { checkAccount, onAccountChecked, onUnlinkedAccount, retryAccountCheck } from './lib/api'
import { initAuth, onTokenRefresh } from './lib/auth'
import { useUserStore } from './stores/user'

async function start() {
  const claims = await initAuth()
  // Le routeur mémorise l'adresse à sa création : créé avant la connexion, il remettrait dans
  // l'adresse le #state=…&code=… que keycloak-js vient de retirer
  const { default: router, routeApresConnexion } = await import('./router')

  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)

  const user = useUserStore(pinia)
  user.setFromToken(claims)
  onTokenRefresh((refreshed) => user.setFromToken(refreshed))

  // Compte refusé par l'API (absent de app.utilisateur), au démarrage ou plus tard :
  // la page « compte non rattaché » remplace les écrans de données (garde du routeur)
  onUnlinkedAccount(() => {
    user.unlinked = true
    void router.replace({ name: 'unlinked-account' })
  })
  // Sites attribués : un GESTION-SITE n'agit que sur ceux-là (US7)
  onAccountChecked((moi) => (user.sites = moi.sites))
  // Avant le premier affichage : l'API accepte-t-elle le jeton et connaît-elle le compte ?
  // Sans réponse, l'application s'affiche quand même et l'appel est relancé en arrière-plan
  if ((await checkAccount()) === 'unavailable') void retryAccountCheck()

  app.use(router)
  // US6 : une seule fois, avant le premier affichage. La garde du routeur ne
  // le refait pas, pour qu'un clic sur « Vue d'ensemble » y reste.
  await router.isReady()
  const arrivee = routeApresConnexion(router.currentRoute.value.name, user.sites)
  if (arrivee) await router.replace(arrivee)
  app.mount('#app')
}

start().catch((error: unknown) => {
  console.error(error)
  const root = document.getElementById('app')
  if (root) {
    root.textContent = 'Le service de connexion est indisponible. Réessayez dans quelques instants.'
  }
})
