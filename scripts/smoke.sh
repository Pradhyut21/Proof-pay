#!/usr/bin/env bash
# One-command offline smoke: generate, verify, export, import into the API, attempt, report.
set -euo pipefail
source "$(dirname "$0")/common.sh"
exec "${PY[@]}" scripts/smoke.py "$@"
