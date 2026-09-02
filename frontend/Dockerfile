# syntax=docker/dockerfile:1
# dev: Vite dev server with HMR (source bind-mounted). prod: static build served by Caddy.

FROM node:26-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# prod: only the built files; the prod overlay copies /app/dist into the caddy volume.
FROM alpine:3.20 AS prod
COPY --from=build /app/dist /srv/frontend
CMD ["sh", "-c", "cp -r /srv/frontend/. /out/ && echo 'frontend dist exported'"]
