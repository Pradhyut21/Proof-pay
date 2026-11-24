#!/usr/bin/env bash
# PanelProof entry point for Linux, macOS and WSL.   ./run.sh <command>
set -euo pipefail
cd "$(dirname "$0")"
source scripts/common.sh
TOKEN="${PANELPROOF_REVEAL_TOKEN:-local-dev-token-0123}"
cmd="${1:-help}"; shift || true
case "$cmd" in
  bootstrap) scripts/bootstrap.sh ;;
  check)     # the standard gate: format, lint, test and build for all three languages
    cargo fmt --all -- --check
    cargo clippy --locked --workspace --all-targets -- -D warnings
    cargo test --locked --workspace
    "${PY[@]}" -m ruff check python scripts
    "${PY[@]}" -m pytest -q python/tests
    (cd apps/web && pnpm lint && pnpm typecheck && pnpm format:check && pnpm test && pnpm build) ;;
  fmt)       cargo fmt --all; "${PY[@]}" -m ruff check --fix python scripts; (cd apps/web && pnpm format) ;;
  smoke)     scripts/smoke.sh "$@" ;;
  dataset)   scripts/build_dataset.sh "$@" ;;
  audit)     scripts/audit_dataset.sh "$@" ;;
  reproduce) scripts/reproduce.sh "$@" ;;
  api)       PANELPROOF_REVEAL_TOKEN="$TOKEN" cargo run --locked -p panelproof-api -- "${1:-data/demo}" "${2:-data/runs/demo.sqlite}" ;;
  web)       (cd apps/web && PANELPROOF_REVEAL_TOKEN="$TOKEN" pnpm dev) ;;
  e2e)       (cd apps/web && PANELPROOF_REVEAL_TOKEN="$TOKEN" pnpm build && pnpm e2e) ;;
  *) cat <<'USAGE'
commands: bootstrap | check | fmt | smoke [--web] | dataset | audit | reproduce | api [dir sqlite] | web | e2e
  api   serves data/demo on 127.0.0.1:3001; web serves the UI on 127.0.0.1:3000 (run them in two terminals)
USAGE
  ;;
esac
