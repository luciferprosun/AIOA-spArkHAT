#!/usr/bin/env bash
set -euo pipefail
umask 077
AIOA_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 -B "$AIOA_SCRIPT_DIR/installer.py" "$@"
