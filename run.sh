#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Studio not installed. Run bash setup.sh' >&2
  exit 1
fi
exec .venv/bin/python -m morphorum_studio "$@"
