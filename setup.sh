#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
  elif command -v python3.13 >/dev/null 2>&1; then
    python3.13 -m venv .venv
  else
    echo 'Python 3.12 or 3.13 is required.' >&2
    exit 1
  fi
fi
.venv/bin/python -m pip install -e .
.venv/bin/python -m morphorum_studio --version
echo '[PASS] Morphorum Studio installed. Run bash run.sh'
