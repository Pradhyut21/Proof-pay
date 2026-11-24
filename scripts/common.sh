# Sourced by the other scripts. Resolves the Python command (uv when available, else the active python).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.cargo/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
  PY=(uv run --project python --python 3.11 --locked python)
else
  export PYTHONPATH="$ROOT/python/src${PYTHONPATH:+:$PYTHONPATH}"
  PY=(python3)
  command -v python3 >/dev/null 2>&1 || PY=(python)
fi
PP=("${PY[@]}" -m panelproof.cli)
