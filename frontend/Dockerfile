# syntax=docker/dockerfile:1

FROM node:24-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./

RUN --mount=type=cache,target=/root/.npm npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src/ ./src/
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist/ /usr/share/nginx/html/

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=5s --start-period=5s --retries=12 \
    CMD wget -q -O /dev/null -T 3 http://127.0.0.1:8080/healthz || exit 1
