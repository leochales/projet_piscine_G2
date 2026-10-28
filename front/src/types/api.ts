// Réponses de l'API, telles qu'elle les renvoie (champs en snake_case).

/** GET /api/sites/derniere-mesure (api/routers/mesures.py, modèle DerniereMesure) */
export interface DerniereMesureApi {
  id_site: string
  nom: string
  type: string
  capacite_kw: number
  seuil_alerte_pct: number // seuil d'alerte du site, en % de la capacité
  horodatage: string
  consommation_kw: number | null
  data_quality: 'good' | 'partial' | 'degraded' | 'critical'
}

/** GET /api/sites/{id_site}/consommation (modèle ConsommationHoraire) */
export interface ConsommationHoraireApi {
  heure: string
  consommation_kwh: number | null
  cout_eur: number | null
  nb_imputees: number // minutes de l'heure reconstituées par imputation (valeurs estimées)
  taux_couverture: number // part des 60 minutes qui ont une consommation, mesurée ou imputée
}

/**
 * GET /api/sites/{id_site}/predictions?horizon=24h|7j (api/routers/predictions.py, modèle
 * Prediction). Les heures à venir, de l'heure pleine qui suit jusqu'à l'horizon.
 */
export interface PredictionApi {
  heure: string // début de l'heure prévue
  consommation_kwh: number
  // Fourchette : null si le modèle n'en donne pas (prévision de référence)
  consommation_basse_kwh: number | null
  consommation_haute_kwh: number | null
  pic_prevu: boolean
  // Maximum de l'heure et sa fourchette : null si le modèle ne les calcule pas
  pic_prevu_kw: number | null
  pic_bas_kw: number | null
  pic_haut_kw: number | null
  calculee_le: string
  version_modele: string
}

export type CapteurApi = 'consumption' | 'electrical' | 'temperature' | 'humidity' | 'network'

/** GET /api/sites/etat (modèle EtatSite) : transmission et capteurs de chaque site (US4) */
export interface EtatSiteApi {
  id_site: string
  nom: string
  derniere_mesure_le: string | null // null : le site n'a jamais transmis
  collecte_a_jour: boolean // faux : panne de notre côté (ETL, API Mock), pas du site
  transmet: boolean | null // null : inconnu, la collecte n'est pas à jour
  etat_capteurs: 'ok' | 'degraded' | 'critical' | null // null : jamais lu
  capteurs_en_panne: CapteurApi[]
  retablissement_prevu: string | null
}
// Elles sont converties vers les types du dashboard (types/energy.ts) dans src/lib/.
// À garder identiques aux modèles Pydantic de api/routers/.

/** GET /api/moi (api/routers/utilisateurs.py, modèle Moi) */
export interface MoiApi {
  id: string // identifiant Keycloak
  id_client: number | null
  roles: string[]
  sites: string[] // sites attribués (rôles *-SITE), vide pour un rôle *-CLIENT
}

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

/** GET /api/alertes (api/routers/alertes.py, modèle Alerte) */
export interface AlerteApi {
  id_alerte: number
  id_site: string
  nom_site: string
  source: 'api_mock' | 'etl' | 'modele'
  // threshold : dépassement du seuil de consommation du site (US3)
  type: 'spike' | 'threshold' | 'anomaly' | 'outage' | 'sensor' | 'predicted_peak'
  severite: 'low' | 'medium' | 'high' | 'critical'
  message: string | null
  debut: string // ISO 8601 : heure du dépassement
  fin: string | null // null : alerte en cours
  valeur: number | null // maximum atteint pendant l'alerte (kW)
  seuil: number | null // seuil dépassé (kW)
  prise_en_compte: boolean
  prise_par: string | null // identifiant Keycloak (pas de nom)
  prise_le: string | null
}
