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

### Avec Docker Compose (depuis la racine du dépôt)

```bash
docker compose -f compose-local.yml up -d --build front
```

L'application est disponible sur http://localhost:5173 (`FRONT_PORT` dans le `.env`), servie par nginx.

### Avec Docker seul (image de production)

```bash
cd front
docker build -t enervision-front --build-arg VITE_API_URL=http://localhost:8000 .
docker run --rm -p 8080:80 enervision-front
```

L'application est disponible sur http://localhost:8080.

> `VITE_API_URL` est intégrée au moment du build : changer l'URL de l'API demande de reconstruire l'image.
> Derrière Traefik, on pourra utiliser un chemin relatif (`/api`).

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
