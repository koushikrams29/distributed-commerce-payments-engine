#!/usr/bin/env bash
# Writes infra/.env for a public deployment from infra/.env.production.example,
# filling every empty value with a freshly generated secret.
#
#   bash scripts/deploy/create_env.sh my-shop.duckdns.org
#
# Never overwrites an existing infra/.env: the database keeps the password it
# was created with, so a new one would lock every service out.
set -euo pipefail

site_address=${1:?usage: bash scripts/deploy/create_env.sh <domain name>}
cd "$(dirname "$0")/../../infra"

if [[ -e .env ]]; then
  echo "infra/.env already exists; leaving it unchanged." >&2
  exit 1
fi

umask 077
# A template saved on Windows has CRLF endings, and "KEY=\r" would never match.
tr -d '\r' < .env.production.example > .env
sed -i "s|^SITE_ADDRESS=$|SITE_ADDRESS=${site_address}|" .env
for key in POSTGRES_PASSWORD RABBITMQ_PASSWORD JWT_SECRET GRAFANA_ADMIN_PASSWORD; do
  sed -i "s|^${key}=$|${key}=$(openssl rand -hex 24)|" .env
done
# Shorter, because you may share them as the public demo login.
for key in DEMO_ADMIN_PASSWORD DEMO_SHOPPER_PASSWORD; do
  sed -i "s|^${key}=$|${key}=$(openssl rand -hex 8)|" .env
done

if grep -qE '^[A-Z_]+=$' .env; then
  echo "infra/.env still has empty values:" >&2
  grep -E '^[A-Z_]+=$' .env >&2
  exit 1
fi

value() { grep "^$1=" .env | cut -d= -f2-; }
echo "Wrote infra/.env (readable only by you). Keep a copy somewhere safe."
echo "Dashboard login:  admin@example.com / $(value DEMO_ADMIN_PASSWORD)"
echo "Shopper login:    shopper@example.com / $(value DEMO_SHOPPER_PASSWORD)"
echo "Grafana login:    admin / $(value GRAFANA_ADMIN_PASSWORD)"
