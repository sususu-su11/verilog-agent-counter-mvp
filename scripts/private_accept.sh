#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m trusted.verify_manifest
python3 -m unittest discover -s tests -v
if ! command -v docker >/dev/null; then
  echo 'DOCKER REQUIRED: stopped before container integration tests' >&2
  exit 1
fi
python3 -m scripts.real_sandbox_regression
python3 -m scripts.private_accept
