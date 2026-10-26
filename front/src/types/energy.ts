// Données affichées par le dashboard. Elles viendront de l'API (schéma gold) ;
// en attendant, src/mocks/ fournit des valeurs proches du wireframe.

export type SiteType = 'bureaux' | 'usine' | 'data_center' | 'hopital' | 'entrepot' | 'laboratoire'

export interface Site {
  id: string
  nom: string
  type: SiteType
  capaciteKw: number
}

export type DataQuality =
  { statut: 'bonne' } | { statut: 'partielle'; heuresManquantes: number } | { statut: 'mauvaise' }

export interface PredictedPeak {
  horodatage: string // ISO 8601
  pourcentageCapacite: number
}

export interface SiteOverview {
  site: Site
  // null : pas de mesure, l'API Mock renvoie consumption_kw: null quand le capteur est en panne
  consommationKw: number | null
  picPrevu: PredictedPeak | null // seulement s'il dépasse le seuil d'alerte
  qualite: DataQuality
}

export interface FleetKpis {
  // Somme des sites qui ont une mesure : ceux qui n'en ont pas sont exclus du total
  consommationKw: number
  nbSites: number
  nbSitesSansMesure: number
  coutJourEur: number
  variationCoutPct: number // par rapport à la veille
  co2JourTonnes: number
}

export interface ConsumptionPoint {
  horodatage: string
  kw: number
}

export interface PredictionPoint {
  horodatage: string
  kw: number
  basseKw: number // fourchette basse
  hauteKw: number // fourchette haute
}

/** Évolution du parc, pour les mini-courbes des KPI */
export interface FleetTrend {
  // Consommation du parc heure par heure sur les dernières 24 h (sites mesurés seulement)
  consommationKw24h: number[]
  // Coût de chacun des 7 derniers jours, du plus ancien au plus récent
  coutEurJours7: number[]
}

export interface SiteSeries {
  mesures: ConsumptionPoint[]
  predictions: PredictionPoint[]
}

export type Severity = 'critique' | 'moyenne' | 'faible'

export type AlertType = 'spike' | 'threshold' | 'anomaly' | 'outage' | 'sensor' | 'predicted_peak'

// Venue de GET /api/alertes (types/api.ts), convertie par lib/alerts.ts
export interface Alert {
  id: string
  siteId: string
  nomSite: string
  type: AlertType
  gravite: Severity
  message: string
  debut: string // ISO 8601 : heure du dépassement ou du début de l'alerte
  // Mesure et seuil, en kW : affichés pour un dépassement de seuil (US3)
  valeurKw: number | null
  seuilKw: number | null
  priseEnCompte: boolean
  // Qui l'a prise en compte et quand (app.alerte_etat : prise_par, prise_le) : que chacun
  // sache qui traite quoi (US7). Absents tant qu'elle n'est pas prise en compte.
  prisePar?: string
  priseLe?: string // ISO 8601
}

export type RecommendationStatus = 'proposee' | 'acceptee' | 'refusee'

// Venue de GET /api/recommandations (types/api.ts), convertie par lib/recommendations.ts
export interface Recommendation {
  id: string
  siteId: string
  nomSite: string
  titre: string // action proposée
  description: string | null
  alerteId: string | null // alerte qui a déclenché la recommandation
  // null : gain pas encore estimé par la règle
  gainEstimeEur: number | null
  periodeGain: 'unique' | 'semaine' | null
  statut: RecommendationStatus
  creeeLe: string // ISO 8601
  decideeLe: string | null // ISO 8601, null tant que personne n'a décidé
}
