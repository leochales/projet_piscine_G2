# Front EnerVision

Tableau de bord web d'EnerVision (Vue 3, Vite, TypeScript, composants shadcn-vue). Il affiche la consommation des sites, les prévisions, les alertes et les recommandations, à partir de l'API (`/api`). Il ne lit jamais la base directement.

## Écrans

| Écran | Adresse | Ce qu'il montre | Routes de l'API |
|---|---|---|---|
| Vue d'ensemble | `/` | Indicateurs du parc : consommation actuelle (avec la courbe des 24 dernières heures), coût du jour (et des 7 derniers jours), CO₂ du jour, alertes actives, économies réalisées. Tableau des sites : dernière mesure, charge par rapport au seuil d'alerte, qualité des données, prochain pic prévu. Bandeau des sites qui ne transmettent plus | `GET /sites/derniere-mesure`, `GET /sites/etat`, `GET /sites/{id}/consommation`, `GET /sites/{id}/predictions`, `GET /alertes`, `GET /recommandations` |
| Site | `/sites/{id}` | Courbe de consommation réelle et courbe prévue avec sa fourchette, sur 24 h ou 7 jours. Pic prévu comparé au seuil du site. Alertes et recommandations du site, avec les actions. Qualité des données, coût et CO₂ sur 7 jours, état de la transmission et des capteurs | `GET /sites/{id}/consommation`, `GET /sites/{id}/predictions`, `GET /alertes?id_site=`, `GET /recommandations?id_site=`, `GET /sites/etat` |
| Alertes | `/alertes` | Alertes actives de tous les sites visibles, filtrables par gravité. Recommandations en cours. Économies réalisées ce mois-ci | `GET /alertes`, `GET /recommandations` |
| Compte non rattaché | `/compte-non-rattache` | Compte Keycloak sans ligne dans `app.utilisateur` (l'API répond 403) | `GET /moi` |
| Accès refusé | `/acces-refuse` | Compte sans rôle `GESTION-*` ni `CONSULT-*` | |

Avec `GESTION-CLIENT` ou `GESTION-SITE`, les boutons « Prendre en compte » (alerte) et « Accepter » / « Refuser » (recommandation) appellent `POST /alertes/{id}/prise-en-compte` et `POST /recommandations/{id}/decision`. Ils n'apparaissent que sur les sites que l'utilisateur gère. Un utilisateur qui n'a qu'un site arrive directement sur la page de ce site après la connexion.

Les économies réalisées sont calculées par le front (`src/stores/operations.ts`) : somme des gains estimés des recommandations acceptées depuis le 1er du mois.

Les données se rafraîchissent toutes les minutes (`src/lib/refresh.ts`), comme la collecte de l'ETL. Chaque bloc affiche l'heure de ses données (`DataFreshness`). Les valeurs sont en kWh et en euros. Le coût vient de l'API (prix du kWh `PRIX_KWH_EUR`). Le CO₂ est calculé par le front avec un facteur fixe de 0,052 kg/kWh (`src/lib/mesures.ts`), car l'API Mock ne fournit pas cette donnée.

Tous les appels passent par `src/services/dashboard.ts`. Le tableau `SOURCES` de ce fichier indique pour chaque donnée si elle vient de l'API ou de données simulées (`src/mocks/`). Toutes les données viennent aujourd'hui de l'API. Les données simulées ne servent plus qu'aux tests et au développement des écrans.

## Lancer le front

### En développement

Depuis la racine du dépôt, créer le `.env` (une seule fois) :

```bash
cp env.example .env
```

Puis :

```bash
cd front
npm install
npm run dev
```

L'application est disponible sur http://localhost:5173, avec rechargement à chaud.
Les appels à `/api` et à `/auth` (Keycloak) sont transmis à Traefik (http://localhost) : lancer aussi la pile Docker ci-dessous, sans quoi la connexion est impossible.

### Connexion

Le dashboard exige une connexion : un visiteur non connecté est redirigé vers la page de Keycloak (realm `enervision`, client `enervision-front`), puis revient sur la page demandée. Le jeton reste en mémoire et se renouvelle tout seul.

Pour se connecter en local, utiliser les comptes de démonstration, créés automatiquement par l'API au démarrage (un par rôle, liste et mot de passe dans le [README racine](../README.md#comptes-de-démonstration)). Un autre compte se crée dans la console d'administration de Keycloak (http://localhost/auth/admin), avec au moins un rôle `GESTION-*` ou `CONSULT-*`, puis s'enregistre dans `app.utilisateur` (voir `infra/runner.md`, « Créer un compte »).

Juste après la connexion, le front appelle `GET /api/moi` (`checkAccount`, `src/lib/api.ts`) : l'API vérifie le jeton et cherche le compte dans `app.utilisateur`. Un compte créé dans Keycloak sans cette ligne n'est rattaché à aucune entreprise : l'API répond 403 et le front affiche la page « Compte non rattaché » à la place des écrans (enregistrement du compte : `infra/runner.md`, « Créer un compte »). Si l'API est injoignable, l'application démarre quand même.

| Rôle | Accès |
|---|---|
| `GESTION-CLIENT`, `GESTION-SITE` | Tous les écrans, actions sur les alertes et recommandations |
| `CONSULT-CLIENT`, `CONSULT-SITE` | Tous les écrans, en lecture seule |
| `MONITORING` ou aucun rôle | Page « Accès refusé » |

Variables facultatives (valeurs par défaut adaptées à Traefik) : `VITE_KEYCLOAK_URL` (`/auth`), `VITE_KEYCLOAK_REALM` (`enervision`), `VITE_KEYCLOAK_CLIENT_ID` (`enervision-front`).

### Avec Docker Compose (depuis la racine du dépôt)

```bash
docker compose -f compose-local.yml up -d --build
```

L'application est disponible sur http://localhost, servie par nginx derrière Traefik (`HTTP_PORT` dans le `.env`).

### Avec Docker seul (image de production)

```bash
cd front
docker build -t enervision-front --build-arg VITE_API_URL=/api .
docker run --rm -p 8080:8080 enervision-front
```

L'image tourne sans root (utilisateur `nginx` de l'image, uid 101) : nginx écoute donc sur le port 8080, pas 80. L'application est disponible sur http://localhost:8080, mais sans Keycloak à la même adresse la connexion échoue : cette commande sert surtout à vérifier que l'image se construit.

> `VITE_API_URL` est intégrée au moment du build : changer l'URL de l'API demande de reconstruire l'image.
> Le chemin relatif `/api` fonctionne derrière Traefik, où le front et l'API partagent la même origine.

## Commandes

| Commande | Effet |
|---|---|
| `npm run dev` | Serveur de développement |
| `npm run build` | Vérification des types + build de production dans `dist/` |
| `npm run preview` | Sert le build de `dist/` en local |
| `npm run test:unit` | Tests Vitest (mode watch ; `-- --run` pour une seule passe) |
| `npm run type-check` | Vérification des types avec `vue-tsc` |
| `npm run lint` | Oxlint puis ESLint, avec correction automatique |
| `npm run format` | Formatage Prettier de `src/` |
