#!/usr/bin/env bash
# bootstrap.sh — one-time dev environment setup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Installing Python dependencies"
pip install -r "$ROOT/requirements.txt"

echo "==> Copying .env.example → .env (if not present)"
if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "     Created .env — fill in secrets before running."
fi

echo "==> Creating rcm_workflow database (if not exists)"
mysql -u"${WORKFLOW_DB_USER:-root}" -p"${WORKFLOW_DB_PASSWORD:-secret}" \
  -h"${WORKFLOW_DB_HOST:-localhost}" \
  -e "CREATE DATABASE IF NOT EXISTS rcm_workflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "==> Running Alembic migrations"
cd "$ROOT"
alembic upgrade head

echo ""
echo "Bootstrap complete."
echo ""
echo "Start services:"
echo "  uvicorn services.tools_service.app.main:app --port 8001 --reload"
echo "  uvicorn services.orchestration_service.app.main:app --port 8002 --reload"
echo "  python -m services.workflow_service.app.workers.scheduler"
