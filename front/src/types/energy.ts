// Données affichées par le dashboard. Elles viendront de l'API (schéma gold) ;
// en attendant, src/mocks/ fournit des valeurs proches du wireframe.

export type SiteType =
  'bureaux' | 'usine' | 'data_center' | 'hopital' | 'entrepot' | 'laboratoire' | 'commerce'

export interface Site {
  id: string
  nom: string
  // Libellé connu (SiteType) ou le type renvoyé par l'API s'il n'est pas encore traduit
  type: SiteType | (string & {})
  capaciteKw: number
  // Seuil d'alerte en % de la capacité, propre au site (100 pour un data center, 98 pour une
  // usine, 90 sinon). Absent des données simulées : SEUIL_ALERTE_PCT (lib/indicators.ts).
  seuilAlertePct?: number
}

export type DataQuality =
  | { statut: 'bonne' }
  // heuresManquantes : seulement quand on sait combien d'heures ont été estimées
  | { statut: 'partielle'; heuresManquantes?: number }
  | { statut: 'mauvaise' }

export interface PredictedPeak {
  horodatage: string // ISO 8601
  pourcentageCapacite: number
}

export interface SiteOverview {
  site: Site
  // null : pas de mesure, l'API Mock renvoie consumption_kw: null quand le capteur est en panne
  consommationKw: number | null
  // Heure de cette mesure (ISO 8601). Absente des données simulées.
  mesureLe?: string | null
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
  // null : heure sans mesure. La courbe s'interrompt, au lieu de relier les voisines.
  kw: number | null
  // Présents pour une heure venue de l'API : kWh de l'heure et son coût. Sur une heure,
  // les kWh égalent la puissance moyenne en kW, d'où le tracé de la courbe.
  kwh?: number | null
  coutEur?: number | null
  // Minutes de l'heure reconstituées après une panne (US4) : la valeur est en partie estimée
  minutesImputees?: number
  // Part des 60 minutes qui ont une consommation, mesurée ou reconstituée (0 à 1)
  couverture?: number
}

export type Sensor = 'consommation' | 'electrique' | 'temperature' | 'humidite' | 'reseau'

// Venue de GET /api/sites/etat (types/api.ts), convertie par lib/etat.ts (US4)
export interface SiteStatus {
  siteId: string
  nomSite: string
  // 'ok' : le site transmet ; 'muet' : plus de mesure depuis 5 min ; 'inconnu' : notre
  // collecte est arrêtée, on ne peut pas savoir (le site n'est pas mis en cause)
  transmission: 'ok' | 'muet' | 'inconnu'
  derniereMesureLe: string | null // ISO 8601, null : jamais transmis
  capteursEnPanne: Sensor[]
  // null : état des capteurs jamais lu
  etatCapteurs: 'ok' | 'degrade' | 'critique' | null
  retablissementPrevu: string | null // ISO 8601
}

// Venue de GET /api/sites/{id}/predictions (types/api.ts), convertie par lib/predictions.ts
export interface PredictionPoint {
  horodatage: string // début de l'heure prévue
  kw: number // moyenne de l'heure
  // Fourchette de la moyenne, null si le modèle n'en donne pas (prévision de référence)
  basseKw: number | null
  hauteKw: number | null
  // Maximum de l'heure et sa fourchette, null si le modèle ne les calcule pas
  picKw: number | null
  picBasKw: number | null
  picHautKw: number | null
  // Vrai quand le modèle prévoit un pic au seuil d'alerte du site : il lève alors l'alerte
  picPrevu: boolean
}

/** Évolution du parc, pour les mini-courbes des KPI */
export interface FleetTrend {
  // Consommation du parc heure par heure sur les dernières 24 h.
  // null : au moins un site sans mesure, la courbe s'interrompt.
  consommationKw24h: (number | null)[]
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
