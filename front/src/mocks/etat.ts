// Transmission et capteurs simulés, au format de GET /api/sites/etat (types/api.ts) :
// un site qui ne transmet plus et un capteur en panne, pour voir le bandeau et la page du site.

import type { EtatSiteApi } from '@/types/api'

const ilYA = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString()
const dans = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString()

const site = (id_site: string, nom: string, champs: Partial<EtatSiteApi> = {}): EtatSiteApi => ({
  id_site,
  nom,
  derniere_mesure_le: ilYA(1),
  collecte_a_jour: true,
  transmet: true,
  etat_capteurs: 'ok',
  capteurs_en_panne: [],
  retablissement_prevu: null,
  ...champs,
})

export const etats = (): EtatSiteApi[] => [
  site('SITE001', 'Siège de Paris'),
  site('SITE002', 'Usine de Lyon'),
  site('SITE003', 'Data center de Lille', {
    derniere_mesure_le: ilYA(42),
    transmet: false,
    etat_capteurs: 'critical',
    capteurs_en_panne: ['network'],
    retablissement_prevu: dans(20),
  }),
  site('SITE004', 'Hôpital de Nantes'),
  site('SITE005', 'Entrepôt de Rennes', {
    etat_capteurs: 'degraded',
    capteurs_en_panne: ['temperature'],
  }),
  site('SITE006', 'Bureaux de Bordeaux'),
  site('SITE007', 'Laboratoire de Grenoble'),
]
