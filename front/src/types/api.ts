// Réponses de l'API, telles qu'elle les renvoie (champs en snake_case).

/** GET /api/sites/derniere-mesure (api/routers/mesures.py, modèle DerniereMesure) */
export interface DerniereMesureApi {
  id_site: string
  nom: string
  type: string
  capacite_kw: number
  horodatage: string
  consommation_kw: number | null
  data_quality: 'good' | 'partial' | 'degraded' | 'critical'
}

/** GET /api/sites/{id_site}/consommation (modèle ConsommationHoraire) */
export interface ConsommationHoraireApi {
  heure: string
  consommation_kwh: number | null
  cout_eur: number | null
}
// Elles sont converties vers les types du dashboard (types/energy.ts) dans src/lib/.
// À garder identiques aux modèles Pydantic de api/routers/.

/** GET /api/recommandations (api/routers/recommandations.py, modèle Recommandation) */
export interface RecommandationApi {
  id_recommandation: number
  id_site: string
  nom_site: string
  id_alerte: number | null // alerte qui a déclenché la recommandation
  regle: string
  titre: string // action proposée
  description: string | null
  date_creation: string // ISO 8601
  // Tous deux null si le gain n'est pas estimé
  gain_estime_eur: number | null
  periode_gain: 'unique' | 'semaine' | null
  statut: 'proposee' | 'acceptee' | 'refusee'
  decide_par: string | null // identifiant Keycloak
  decide_le: string | null
}
