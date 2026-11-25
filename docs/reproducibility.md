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

## Artifact hashes and decoded pixels

The manifest commits the SHA-256 of each PNG in the dataset image set as written, alongside the other committed public and private artifacts. A rebuild audit compares the regenerated manifest. For exact replay, match the source revision, seed, configurations, Python environment, and native rendering, encoding, and verification libraries. Platform smoke tests establish that the pipeline runs in each tested environment. [Manifest and rebuild audit](../python/src/panelproof/export.py) · [PNG renderer](../python/src/panelproof/render.py)

Different PNG encoding builds can produce different file bytes for the same decoded pixels. The audit will still report byte drift. To diagnose it, compare PNGs for the same logical scene or task with the OpenCV color decoder used by the verifier. Run this in the synced project Python environment with the two local paths.

PNG bytes determine image filenames and hashes in the exported JSONL. Encoding drift can therefore change several manifest entries even when pixel comparisons pass. The v0.3 expanded hash is evidence from one build environment. The reported cross-environment expanded build mismatch has yet to be traced to a specific cause. Compose runs the judge console and its sample bundle.

```python
from hashlib import sha256
from pathlib import Path

import cv2
import numpy as np

def image_evidence(path):
    data = Path(path).read_bytes()
    pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ValueError(f"PNG could not be decoded: {path}")
    return sha256(data).hexdigest(), pixels

left_hash, left_pixels = image_evidence("/local/original.png")
right_hash, right_pixels = image_evidence("/local/rebuild.png")
print("Encoded SHA-256 match", left_hash == right_hash)
print("Decoded pixels match", np.array_equal(left_pixels, right_pixels))
```

Record both results with the platform and library versions. The verifier retains the encoded image hash in its trace and recovers readings from the decoded pixels. Preserve the original frozen images for measured replay because C1 provenance commits the exact bytes sent with the prompt. [Raster verifier](../python/src/panelproof/verify.py) · [Evaluation conditions](../evals/conditions.md)

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
uv run --project python --python 3.11 --locked python -m panelproof.cli build-dataset --config configs/benchmark-dual-rule.yaml --out /local/holdout-v040 --holdout-seed-file /local/v040-seed.txt
uv run --project python --python 3.11 --locked python -m panelproof.cli audit-dataset --dataset /local/holdout-v040 --rebuild-config configs/benchmark-dual-rule.yaml --holdout-seed-file /local/v040-seed.txt
```

Use absolute paths appropriate to your platform. The v0.4 configuration includes all three layouts and both operating-state rules. The builder without a holdout seed file creates a public reproducibility build. Prepare and pin the new cohort with the [measured evaluation procedure](../evals/conditions.md#measured-runs-need-a-freeze). The v0.2 configuration remains available at `configs/benchmark.yaml`.

The recorded private v0.4 rebuild matched the original manifest on Windows x64 with Python 3.11.15, Pillow 12.3.0 (PNG zlib codec `1.3.1.zlib-ng`), and OpenCV 5.1.0. Both runs used the same configuration and private seed.

## Build the expanded layout dataset

The expanded generator adds a side-by-side two-pump layout with stacked gauges. The commands below produce and audit the public v0.3 configuration. The prior `configs/benchmark.yaml` remains available for reproducing v0.2.

```sh
uv run --project python --python 3.11 --locked python -m panelproof.cli build-dataset --config configs/benchmark-expanded.yaml --out data/build/expanded
uv run --project python --python 3.11 --locked python -m panelproof.cli audit-dataset --dataset data/build/expanded --rebuild-config configs/benchmark-expanded.yaml
```

## Prepare an archive

From a Git checkout, create the source ZIP from the intended commit and record the checksum. Keep the [submission checklist](../submission/DELIVERABLE.md) alongside the approved samples, evidence, and presentation.
