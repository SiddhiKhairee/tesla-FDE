# ---- build stage ----
# Node version this project was built/tested against (via nvm) — see
# package.json/package-lock.json for pinned dependency versions.
FROM node:24-slim AS build

WORKDIR /app

# Install deps first so this layer is cached separately from source changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- serve stage ----
# Only the built static output leaves the build stage — no node_modules or
# source files in the final image.
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
# Reverse-proxies /tickets, /pipeline, /reports, /health to the backend
# service (assumed reachable as "backend" — see nginx.conf) so the built
# dashboard can reach the API without a dev-only Vite proxy.
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
