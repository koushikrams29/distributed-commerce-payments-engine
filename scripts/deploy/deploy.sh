#!/usr/bin/env bash
# Builds and (re)starts the production stack from the current main branch.
# The same command does the first deploy and every update: images whose source
# changed are rebuilt, migration jobs run, and only changed services restart.
#
#   bash scripts/deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
git pull --ff-only

cd infra
if [[ ! -f .env ]]; then
  echo "infra/.env is missing; create it first: bash scripts/deploy/create_env.sh <domain name>" >&2
  exit 1
fi

docker compose -f docker-compose.yml -f docker-compose.app.yml -f docker-compose.prod.yml \
  up -d --build --remove-orphans --wait --wait-timeout 600
# Each rebuild leaves the previous images behind; a small disk fills up quickly.
docker image prune -f >/dev/null

site_address=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2-)
echo "Deployed. Open https://${site_address}"
