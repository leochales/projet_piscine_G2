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

export interface Alert {
  id: string
  siteId: string
  gravite: Severity
  message: string
  priseEnCompte: boolean
  // Qui l'a prise en compte et quand (app.alerte_etat : prise_par, prise_le) : que chacun
  // sache qui traite quoi (US7). Absents tant qu'elle n'est pas prise en compte.
  prisePar?: string
  priseLe?: string // ISO 8601
}

export type RecommendationStatus = 'proposee' | 'acceptee' | 'refusee'

export interface Recommendation {
  id: string
  siteId: string
  titre: string
  alerteLiee: string | null
  gainEstimeEur: number
  periodeGain: 'ponctuel' | 'semaine'
  statut: RecommendationStatus
}
