# Front EnerVision

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

Le dashboard exige une connexion : un visiteur non connecté est redirigé vers la page de Keycloak (realm `enervision`, client `enervision-front`), puis revient sur la page demandée. Les comptes se créent dans la console d'administration (http://localhost/auth/admin), avec au moins un rôle `GESTION-*` ou `CONSULT-*` pour accéder aux écrans. Le jeton reste en mémoire et se renouvelle tout seul.

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
docker run --rm -p 8080:80 enervision-front
```

L'application est disponible sur http://localhost:8080, mais sans Keycloak à la même adresse la connexion échoue : cette commande sert surtout à vérifier que l'image se construit.

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
