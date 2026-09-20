#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -c backend/requirements.lock -e './backend[dev]'
if [[ ! -d frontend/node_modules ]]; then
  npm ci --prefix frontend
fi
pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
.venv/bin/uvicorn troubleshooter.api.agent:create_app --factory --host 127.0.0.1 --port 8001 &
pids+=("$!")
.venv/bin/uvicorn troubleshooter.api.public:create_app --factory --host 127.0.0.1 --port 8000 &
pids+=("$!")
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1) &
pids+=("$!")
wait
