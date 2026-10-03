#!/usr/bin/env bash
set -euo pipefail
umask 077
repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repository_root"
if [[ "$(git branch --show-current)" != "nebius-personal-ai" ]]; then
  echo "STOP: demo requires branch nebius-personal-ai" >&2
  exit 1
fi
if [[ -x "$repository_root/.venv/bin/python" ]]; then
  demo_python="$repository_root/.venv/bin/python"
else
  demo_python="$(command -v python3)"
fi
export PYTHONPATH="$repository_root/runtime:$repository_root"
export PYTHONDONTWRITEBYTECODE=1
"$demo_python" -B -c 'import runtime.personal_ai_demo_launcher' >/dev/null
demo_has_state=0
for demo_argument in "$@"; do
  case "$demo_argument" in --state-dir|--state-dir=*) demo_has_state=1 ;; esac
done
if [[ "$demo_has_state" == 0 ]]; then
  demo_state_dir="$(mktemp -d "${TMPDIR:-/tmp}/aioa-nebius-demo.XXXXXXXX")"
  exec "$demo_python" -B -m runtime.personal_ai_demo_launcher --state-dir "$demo_state_dir" "$@"
fi
exec "$demo_python" -B -m runtime.personal_ai_demo_launcher "$@"
