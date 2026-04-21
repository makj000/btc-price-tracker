#!/bin/zsh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  exec "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/menubar_app.py"
fi

exec python3 "$PROJECT_ROOT/scripts/menubar_app.py"
