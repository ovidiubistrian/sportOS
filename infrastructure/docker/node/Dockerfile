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
RUN pnpm --filter "./${APP_DIR}" build


# Static assets only — the SPA has no server runtime. In production these are
# served from a CDN; this stage exists for preview environments and CI.
FROM nginx:alpine AS prod
ARG APP_DIR=apps/admin-web
COPY --from=build /repo/${APP_DIR}/dist /usr/share/nginx/html
COPY infrastructure/docker/node/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
