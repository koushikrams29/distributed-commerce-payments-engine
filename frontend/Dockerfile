# syntax=docker/dockerfile:1
#   docker build -t commerce/frontend frontend

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build


# Runs as a non-root user and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.30-alpine
# The image's entrypoint renders templates with envsubst at start, so one image
# works against any gateway address.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
# Every variable the template uses needs a value here: the entrypoint only
# substitutes variables that are set, and would leave "${JAEGER_UI_URL}" as text.
ENV GATEWAY_URL=http://gateway:8001 \
    TRUSTED_PROXY=127.0.0.1 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    JAEGER_UI_URL=http://localhost:16686 \
    GRAFANA_UI_URL=http://localhost:3000 \
    RABBITMQ_UI_URL=http://localhost:15672
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
