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
# Applique les correctifs de sécurité d'Alpine publiés depuis la dernière image nginx
# hadolint ignore=DL3017
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
