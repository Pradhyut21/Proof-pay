# PanelProof

PanelProof is a visual benchmark for reading and reasoning over fictional pump panels. Its synthetic data is used for evaluation of existing vision-language models. See the [PRD](PRD.md), [repository contract](reference/CONTRACT.md), and [GitHub work plan](https://github.com/Pradhyut21/Proof-pay/issues/1).

## Check the implementation

Install Rust stable, Python 3.11 with uv, and Node.js 22 or newer. Run these commands from the repository root.

```sh
uv sync --project python --python 3.11 --locked
uv run --project python --python 3.11 --locked pytest -q
uv run --project python --python 3.11 --locked ruff check python scripts
cargo test --locked --workspace
cargo build --locked -p panelproof-scoring --bin pp
uv run --project python --python 3.11 --locked python scripts/check_solver_parity.py
node --test apps/web/lib/contracts.test.mjs
```

The [offline evaluator](evals/runner.md) and [local Axum API](docs/api.md) have separate usage instructions. Rule parity compares structured scene records. Independent validation of rendered panels follows in the [raster verifier issue](https://github.com/Pradhyut21/Proof-pay/issues/9).

If Cargo uses a custom target directory, pass the built `pp` binary path to the parity script with `--pp`.

## Current integration

Schemas, deterministic Python references, Rust checking and scoring, and offline model evaluation have isolated verification paths. The full pilot needs generated panels, counterfactuals, and independent raster traces. The frozen evaluation needs the validated dataset and authorized model access.
