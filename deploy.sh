#!/usr/bin/env bash
# Manual deployment only: no paid cloud provisioning or Inference API calls.
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-}"
if [ "$#" -gt 1 ] || { [ -n "$MODE" ] && [ "$MODE" != "--public-mock" ]; }; then
  echo 'Usage: ./deploy.sh [--public-mock]' >&2; exit 2
fi
[ -f .env ] || { echo 'ERROR: create .env from .env.example first' >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. ./.env
set +a
if [ "$MODE" = "--public-mock" ]; then
  [ "${APP_ENV:-}" = public_mock ] || { echo 'ERROR: --public-mock requires APP_ENV=public_mock' >&2; exit 1; }
  [ "${PUBLIC_BIND_HOST:-}" = 0.0.0.0 ] || { echo 'ERROR: public mock requires PUBLIC_BIND_HOST=0.0.0.0' >&2; exit 1; }
  [ "${PUBLIC_MOCK_ACK:-}" = 1 ] || { echo 'ERROR: public operator opt-in required' >&2; exit 1; }
else
  [ "${APP_ENV:-}" = private ] || { echo 'ERROR: default deploy requires APP_ENV=private' >&2; exit 1; }
  [ "${PUBLIC_BIND_HOST:-127.0.0.1}" = 127.0.0.1 ] || { echo 'ERROR: private must bind loopback' >&2; exit 1; }
fi
: "${DOCKER_HOST_SOCKET:?Configure audited Docker socket path explicitly}"
[ -S "$DOCKER_HOST_SOCKET" ] || { echo 'ERROR: Docker socket unavailable' >&2; exit 1; }
if [ "${USE_LOCAL_SIM:-0}" = 1 ] || [ "${SKIP_MANIFEST:-0}" = 1 ]; then
  echo 'ERROR: unsafe downgrade flags forbidden' >&2; exit 1
fi
# Never write or regenerate the reviewed manifest during deploy.
python3 -m trusted.verify_manifest
python3 -c 'from app.config import validate_startup,require_localhost_binding; validate_startup(); require_localhost_binding()'
if [ "$MODE" = "--public-mock" ]; then
  echo 'Public MOCK ONLY: fixed demo IDs, no arbitrary RTL, no Vultr Inference; check VM/firewall and spending first.'
else
  echo 'Private VM only: SSH tunnel + Basic Auth; check VM credit and spending first.'
fi
docker compose build sandbox backend
docker compose up -d backend
printf 'Endpoint: http://%s:%s/ (APP_ENV=%s)\n' "${PUBLIC_BIND_HOST:-127.0.0.1}" "${PUBLIC_PORT:-8000}" "$APP_ENV"
