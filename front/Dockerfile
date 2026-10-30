# Build
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build-only

# Service statique, routé par Traefik
# 1.30 : branche stable maintenue (1.27 n'a plus de correctifs de sécurité)
FROM nginx:1.30-alpine
# Applique les correctifs de sécurité d'Alpine publiés depuis la dernière image nginx.
# La CI change MAJ_SECURITE à chaque exécution : sans cela, le cache de build reprendrait
# l'ancienne couche tant que l'image nginx ne change pas, et les correctifs ne seraient
# jamais appliqués.
ARG MAJ_SECURITE
# hadolint ignore=DL3017
RUN echo "Correctifs Alpine : ${MAJ_SECURITE:-sans identifiant}" && apk upgrade --no-cache
# nginx sans root (utilisateur nginx de l'image) : PID dans /tmp, cache à lui, et port
# 8080 (un port sous 1024 demanderait des droits root sur certains hôtes)
RUN sed -i -e '/^user /d' -e 's#^pid .*#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# 101 : uid et gid de l'utilisateur nginx de l'image
USER 101:101
EXPOSE 8080
