#!/usr/bin/env bash
# Check the toolchain and install locked dependencies. Offline after the first run.
set -euo pipefail
source "$(dirname "$0")/common.sh"
ok=1
need() { if command -v "$1" >/dev/null 2>&1; then echo "ok      $1 $($1 --version 2>&1 | head -1)"; else echo "MISSING $1 - $2"; ok=0; fi; }
need cargo "install Rust stable from https://rustup.rs"
need node "install Node.js 22 or newer"
need pnpm "npm install -g pnpm (or corepack enable)"
command -v uv >/dev/null 2>&1 && echo "ok      uv $(uv --version)" || echo "note    uv not found; falling back to the active python (needs Python 3.11+ with: pip install -e python)"
[ "$ok" = 1 ] || { echo "bootstrap: install the missing tools above and rerun"; exit 1; }
if command -v uv >/dev/null 2>&1; then uv sync --project python --python 3.11 --locked; fi
(cd apps/web && pnpm install --frozen-lockfile)
cargo fetch --locked
echo "bootstrap: done"
