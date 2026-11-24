# Reproduce PanelProof

Start with the [judge quickstart](../README.md#quickstart) for a browser demonstration. Run commands from the repository root. The default pipeline runs locally on CPU with fixture model attempts.

## Commands

| Task | Linux, macOS, or WSL | Windows PowerShell |
| --- | --- | --- |
| Install locked project dependencies | `./run.sh bootstrap` | `.\run.ps1 bootstrap` |
| Check format, lint, types, tests, and build | `./run.sh check` | `.\run.ps1 check` |
| Run standalone pipeline smoke | `./run.sh smoke` | `.\run.ps1 smoke` |
| Build reproducibility dataset | `./run.sh dataset` | `.\run.ps1 dataset` |
| Audit dataset | `./run.sh audit` | `.\run.ps1 audit` |
| Rebuild, audit and create a DEMO ONLY report | `./run.sh reproduce` | `.\run.ps1 reproduce` |

Build the web app once with `pnpm --dir apps/web build`, then add `--web` to the smoke command to include its routes. The default dataset output is `data/build/main`. Reduce `workers` in [benchmark configuration](../configs/benchmark.yaml) if memory is limited. [Smoke and CI](https://github.com/Pradhyut21/Proof-pay/actions/runs/45449233021) · [Compose and macOS checks](https://github.com/Pradhyut21/Proof-pay/actions/runs/45449232901)

## Start from an extracted source ZIP

After bootstrap, create a local demo bundle before you start the API or Compose. The archive carries the code and documentation. The exact reviewed sample bundle is available in the [Git checkout](https://github.com/Pradhyut21/Proof-pay/tree/main/data/demo).

```sh
uv run --project python --python 3.11 --locked python -m panelproof.cli factory --seed source-demo --count 3 --out data/demo
```

Use the generated task and pair IDs in the browser. The browser test suite uses the checked-in IDs and is intended for a Git checkout.

## Browser rehearsal

Build the API with `cargo build --locked -p panelproof-api`. Create `data/runs` and set `PP_PYTHON` to the Python executable from the synced project environment, as shown in the [quickstart](../README.md#quickstart). Use a fresh `PP_RUNS_DIR` to exercise generation. Then use `./run.sh e2e` or `.\run.ps1 e2e`.

Set `PP_E2E_CHANNEL` to `msedge` or `chrome` for an installed browser. To include the Reports check, first produce an offline report with `reproduce` and point `PANELPROOF_REPORT_ROOT` to the absolute directory containing its `report.json`. For per-task Rust/Python agreement in new Factory output, build `pp` with `cargo build --locked -p panelproof-scoring --bin pp` and set `PANELPROOF_RUST_PP` to its absolute path before starting the web server.

The judge interface reads `data/build/demo_report/report.json` by default. A configured report root may also contain named subfolders, each with a `report.json`. The API and web scripts use loopback addresses. Keep the local reveal token in the server environment.

## Build a private evaluation holdout

Keep a random 64-character hexadecimal seed in a local file outside Git. Choose a new output folder outside Git. Preserve the seed, private answer artifacts, and selection details locally.

```sh
uv run --project python --python 3.11 --locked python -m panelproof.cli build-dataset --config configs/benchmark.yaml --out /local/holdout --holdout-seed-file /local/seed.txt
uv run --project python --python 3.11 --locked python -m panelproof.cli audit-dataset --dataset /local/holdout --rebuild-config configs/benchmark.yaml --holdout-seed-file /local/seed.txt
```

Use absolute paths appropriate to your platform. The builder without a holdout seed file creates a public reproducibility build. Use the [measured evaluation procedure](../evals/conditions.md#measured-runs-need-a-freeze) before submitting performance claims.

## Prepare an archive

From a Git checkout, create the source ZIP from the intended commit and record the checksum. Keep the [submission checklist](../submission/DELIVERABLE.md) alongside the approved samples, evidence, and presentation.
