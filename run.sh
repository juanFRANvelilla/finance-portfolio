#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() {
  echo ""
  echo "Deteniendo procesos..."
  kill "${BACKEND_PID:-0}" "${FRONTEND_PID:-0}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Arrancando backend (FastAPI) en http://localhost:8000"
"$SCRIPT_DIR/backend/run.sh" &
BACKEND_PID=$!

sleep 2

echo "==> Arrancando frontend (Angular) en http://localhost:4200"
"$SCRIPT_DIR/frontend/run.sh" &
FRONTEND_PID=$!

wait
