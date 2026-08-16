FROM node:22-slim AS base

ENV PNPM_HOME=/pnpm
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

WORKDIR /repo


FROM base AS dev

# Manifests first so a source change does not invalidate the install layer.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY packages/config/package.json ./packages/config/
COPY packages/ui/package.json ./packages/ui/
COPY packages/api-client/package.json ./packages/api-client/
COPY apps/admin-web/package.json ./apps/admin-web/
COPY apps/public-web/package.json ./apps/public-web/

RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --no-frozen-lockfile

COPY . .

EXPOSE 5173
CMD ["pnpm", "--filter", "@footbola/admin-web", "dev"]


FROM base AS build

COPY . .
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile
ARG APP_DIR=apps/admin-web

# Vite substitutes `import.meta.env.*` at build time, so the admin bundle
# carries the addresses it was built with and cannot be told them later. Unset,
# `VITE_API_URL` compiles to `undefined` and every request the admin makes
# fails — silently, as an empty dropdown or a sign-in button that does nothing,
# because a missing base URL is not an error the browser reports usefully.
#
# The defaults are the development ones, so a bare `docker build` still
# produces something that works against the local stack.
ARG VITE_API_URL=http://api.footbola.localhost
ARG VITE_OIDC_ISSUER=http://auth.footbola.localhost/realms/football-os
ARG VITE_OIDC_CLIENT_ID=admin-web
ENV VITE_API_URL=$VITE_API_URL \
    VITE_OIDC_ISSUER=$VITE_OIDC_ISSUER \
    VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID

RUN pnpm --filter "./${APP_DIR}" build


# Static assets only — the SPA has no server runtime. In production these are
# served from a CDN; this stage exists for preview environments and CI.
FROM nginx:alpine AS prod
ARG APP_DIR=apps/admin-web
COPY --from=build /repo/${APP_DIR}/dist /usr/share/nginx/html
COPY infrastructure/docker/node/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80


# The public site: a Node server, not static files. Every club's website is
# rendered by this one process and told apart by the Host header, so it cannot
# be pre-rendered to a bucket.
FROM base AS next-build

COPY . .
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile
RUN pnpm --filter "./apps/public-web" build


FROM node:22-slim AS next

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Standalone output carries the exact dependencies the server traced, and
# nothing else. `public` and `.next/static` are not in it and must come along.
COPY --from=next-build /repo/apps/public-web/.next/standalone ./
COPY --from=next-build /repo/apps/public-web/.next/static ./apps/public-web/.next/static
COPY --from=next-build /repo/apps/public-web/public ./apps/public-web/public

RUN useradd --uid 10001 --no-create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 3000
CMD ["node", "apps/public-web/server.js"]
