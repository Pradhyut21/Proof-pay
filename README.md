# PanelProof

PanelProof is a visual benchmark for reading and reasoning over fictional pump panels. Its synthetic data is used for evaluation of existing vision-language models. See the [PRD](PRD.md), [repository contract](reference/CONTRACT.md), and [GitHub work plan](https://github.com/Pradhyut21/Proof-pay/issues/1).

Python generates and verifies panels, Rust serves and scores them, and a Next.js app lets a judge try the tasks. [`docs/architecture.md`](docs/architecture.md) shows how the parts fit.

## Quickstart

Requirements: Rust stable, Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node.js 22+ and pnpm. `./run.sh bootstrap` (Linux, macOS, WSL) or `.\run.ps1 bootstrap` (Windows PowerShell) installs the project dependencies.

```sh
./run.sh bootstrap       # install dependencies
./run.sh smoke           # 16-step end-to-end check (add --web to include the web app)
./run.sh api             # terminal 1: API for data/demo on 127.0.0.1:3001
./run.sh web             # terminal 2: web app on http://127.0.0.1:3000
```

Open `/factory` to build a small dataset and `/arena` to answer tasks and reveal answers. The reveal token is read from `PANELPROOF_REVEAL_TOKEN` (the scripts default to a local development value) and stays on the server.

| Command | What it does |
| --- | --- |
| `./run.sh check` | Format, lint, test and build for Rust, Python and the web app |
| `./run.sh dataset` | Build the dataset described by `configs/benchmark.yaml` into `data/build/main` |
| `./run.sh audit` | Leakage, duplicate, hash and byte-identical rebuild audit |
| `./run.sh reproduce` | Rebuild, audit and write a DEMO ONLY report |
| `./run.sh e2e` | Playwright judge-flow test |

On Windows use `.\run.ps1` with the same command names. The Rust workspace did not build with the GNU toolchain on the Windows machine used here (missing MinGW tools); there, Rust was built and tested in WSL Ubuntu. The MSVC toolchain is the expected native route and was not tested. On low-memory machines set `workers: 1` in `configs/benchmark.yaml` (the default is 4; a one-worker build was not compared against the four-worker manifest). Docker files exist (`compose.yaml`, `infra/docker/`) but were **not run**.

## Checks

```sh
uv sync --project python --python 3.11 --locked
uv run --project python --python 3.11 --locked pytest -q
uv run --project python --python 3.11 --locked ruff check python scripts
cargo test --locked --workspace
cargo build --locked -p panelproof-scoring --bin pp
uv run --project python --python 3.11 --locked python scripts/check_solver_parity.py
pnpm --dir apps/web lint && pnpm --dir apps/web typecheck && pnpm --dir apps/web test
```

If Cargo uses a custom target directory, pass the built `pp` binary path to the parity script with `--pp`.

## Documentation

| Topic | Document |
| --- | --- |
| Architecture and how to extend instruments, rules and models | [`docs/architecture.md`](docs/architecture.md) |
| Task definitions | [`docs/task_card.md`](docs/task_card.md) |
| Dataset contents, splits and limits | [`docs/dataset_card.md`](docs/dataset_card.md) |
| Validation results, perturbation table, parity | [`docs/validation.md`](docs/validation.md) |
| Evaluation protocol, conditions and metrics | [`evals/protocol.md`](evals/protocol.md), [`evals/conditions.md`](evals/conditions.md), [`evals/runner.md`](evals/runner.md) |
| API | [`docs/api.md`](docs/api.md) |
| Source and license audit | [`docs/source_audit.md`](docs/source_audit.md), [`docs/dataset_sources.md`](docs/dataset_sources.md) |
| Self-audit and ranked fixes | [`docs/judge_audit.md`](docs/judge_audit.md) |

## Current status

The dataset, verifier, API, scorer and web app run end to end on synthetic data, and everything under `docs/results/` is reproducible from this repository. **No live model has been evaluated**; all model outputs in reports are DEMO ONLY mock outputs. No human has reviewed the tasks. Known weaknesses (an ALARM-lamp shortcut in consistency tasks, a verifier that is brittle under image perturbation, two layout families) are listed in [`docs/judge_audit.md`](docs/judge_audit.md). The frozen evaluation needs authorized model access.
