# Front Vue 3 (serveur de dev Vite)
FROM node:22-alpine

WORKDIR /app

COPY . .

# Dépendances installées seulement si le projet Vue est initialisé
RUN if [ -f package-lock.json ]; then npm ci; \
    elif [ -f package.json ]; then npm install; fi

EXPOSE 5173

# Lance Vite si package.json existe, sinon le conteneur attend (projet pas encore initialisé)
# --host 0.0.0.0 : rend Vite joignable depuis l'extérieur du conteneur
CMD ["sh", "-c", "if [ -f package.json ]; then exec npm run dev -- --host 0.0.0.0 --port 5173; else echo 'front/package.json absent : front pas encore initialisé'; exec sleep infinity; fi"]
