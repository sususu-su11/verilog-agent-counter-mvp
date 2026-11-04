#!/usr/bin/env bash
# Local mock demo (no Vultr spend). Requires Docker + built sandbox image.
set -euo pipefail
cd "$(dirname "$0")/.."
docker image inspect verilog-sandbox:latest >/dev/null 2>&1 || docker build -t verilog-sandbox:latest ./sandbox
export MOCK_LLM=1 PYTHONPATH="$PWD"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
