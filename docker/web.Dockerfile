# syntax=docker/dockerfile:1
# Web app image: build the Vite app, then serve the static files with Caddy.
# Build context is the repository root:  docker build -f docker/web.Dockerfile .

# --- Stage 1: build web/dist ---------------------------------------------------------------------
FROM node:24-alpine AS build

# Keep in step with the pnpm that wrote web/pnpm-lock.yaml.
ARG PNPM_VERSION=12
RUN npm install --global pnpm@${PNPM_VERSION}

WORKDIR /web

# Dependencies first: this layer is rebuilt only when the manifest or lockfile change.
# pnpm-workspace.yaml holds pnpm settings in recent versions; the pattern also matches nothing,
# so the build works whether or not the file exists.
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yam[l] ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY web/ ./

# Vite replaces import.meta.env.VITE_* with these values at build time. They end up in the
# JavaScript the browser downloads, so only public values belong here.
ARG VITE_API_URL=http://localhost:8080
ARG VITE_SUPABASE_URL=http://localhost:8000
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

RUN pnpm build

# --- Stage 2: static file server -----------------------------------------------------------------
FROM caddy:2-alpine

COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv

EXPOSE 80
