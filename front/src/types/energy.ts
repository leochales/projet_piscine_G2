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
  consommationKw: number
  picPrevu: PredictedPeak | null // seulement s'il dépasse le seuil d'alerte
  qualite: DataQuality
}

export interface FleetKpis {
  consommationKw: number
  nbSites: number
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
