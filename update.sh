#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git rev-parse --is-inside-work-tree >/dev/null
branch="$(git symbolic-ref --quiet --short HEAD)" || {
  echo 'Detached HEAD: select a branch first.' >&2
  exit 1
}
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'Local changes found. Commit or stash them before updating.' >&2
  exit 1
fi
echo "Updating Studio branch: $branch"
git pull --ff-only
bash setup.sh
echo '[PASS] Studio updated.'
