#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$RUNTIME_DIR/.." && pwd)"
VENV_PYTHON="$RUNTIME_DIR/.venv/bin/python"
WEB_FILE="$RUNTIME_DIR/webapp.py"

export PYTHONPATH="$REPO_DIR:$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [[ -x "$VENV_PYTHON" ]]; then
  exec "$VENV_PYTHON" "$WEB_FILE" "$@"
fi

echo "Virtual environment not found. Using system python3 for the web runtime."
exec python3 "$WEB_FILE" "$@"
