#!/usr/bin/env bash
# USO DE ESTE SCRIPT:
#
# 1. Para arrancar en LOCAL (localhost:5432):
#    ./run.sh
#    # o bien: ./run.sh local
#
# 2. Para arrancar en SERVIDOR / PREPRODUCCIÓN (db.postgres.local:30432):
#    ./run.sh server
#    # o bien: ./run.sh pre
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROFILE="${1:-local}"

if [ "$PROFILE" = "server" ] || [ "$PROFILE" = "pre" ]; then
  export APP_PROFILE="server"
  echo "🚀 Arrancando FastAPI en perfil SERVER (Preproducción: db.postgres.local:30432)..."
else
  export APP_PROFILE="local"
  echo "🚀 Arrancando FastAPI en perfil LOCAL (Localhost:5432)..."
fi

if [ ! -d ".venv" ]; then
  echo "Creando entorno virtual .venv..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
else
  source .venv/bin/activate
fi

echo "Servidor disponible en http://localhost:8000 (Documentación: http://localhost:8000/docs)"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
