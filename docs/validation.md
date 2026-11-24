# Validation

This extends [`validation-foundation.md`](validation-foundation.md), which describes the candidate validator interface. Everything below was measured on the committed configuration (`configs/benchmark.yaml`, dataset 0.1.0). Raw outputs are in [`results/`](results/).

## 1. Acceptance gates for a generated scene

A base scene is accepted only if all of these hold (`export.py`):

1. Layout check passes (`render.check_layout`).
2. The independent raster verifier returns `verified` for every pump, using only the PNG.
3. The verifier's recovered readings agree with the scene truth (`validate.compare_trace_to_scene`).

Result for the build: 120 base scenes attempted, 110 accepted (91.7%). Rejections: 4 `INLET:numerals_unreadable`, 15 `make_missing:no_valid_edit`, 4 `make_preserving:no_valid_edit`, 2 `make_semantic_flip:no_valid_edit`. Accepted variants over attempted: 99.5%. See `results/dataset_report.json`.

## 2. Dataset audit (`./run.sh audit`)

`results/dataset_audit.json`, `pass: true`:

| Check | Result |
| --- | --- |
| Groups in more than one split | 0 |
| Images in more than one split | 0 |
| Public records with private fields or seeds | 0 |
| Seed overlap between dev and frozen | 0 |
| Files with hash drift | none |
| Rebuild from config reproduces the manifest | equal (`manifest_sha256` `a6d884a6…8d00`) |
| Layout families on both dev and frozen sides | `1p-single`, `2p-rows` |

**Answer-class shortcut check.** Answer distributions by ALARM lamp state:

- State tasks (n=291): maximum shift 1.3 percentage points. No ALARM shortcut.
- Consistency tasks (n=264): maximum shift **28.0 percentage points**. When ALARM is off, `CONSISTENT` is 64.8% of tasks; when on, `CONTRADICTION` is 63.2%. A model that reads only the ALARM lamp can beat chance on X tasks. X results must be read with this in mind; it is a known limitation, not a resolved one.

## 3. Raster verifier under perturbation

`python -m panelproof.cli perturb --dataset data/build/main --limit 30` renders 30 base scenes and applies each perturbation. The scene truth is regenerated from the private seed. Output: `results/perturbation.json`.

| Perturbation | Verified correct | Rejected | Verified wrong (false accept) |
| --- | --- | --- | --- |
| none | 30 | 0 | 0 |
| brightness −15% | 30 | 0 | 0 |
| Gaussian blur 0.6 | 30 | 0 | 0 |
| brightness +15% | 26 | 4 | 0 |
| JPEG quality 90 | 19 | 11 | 0 |
| glare over panel | 14 | 16 | 0 |
| scale 0.97 | 10 | 20 | 0 |
| Gaussian noise σ=3 | 0 | 30 | 0 |
| rotation 1° | 0 | 30 | 0 |

Reading the table honestly:

- No perturbation produced a wrong accepted reading (0 of 270 images), so failures are safe rejections.
- The verifier does **not** meet a 95% agreement target on six of the eight perturbations. It assumes the rendered geometry. It rejects small rotations, rescaling and pixel noise, and it is fragile to JPEG compression.
- The 30-scene sample is small and drawn from the first 30 accepted base groups, so rates have wide uncertainty. Real photographs are out of scope.
- The first run of this study (before the unit table change to psi = 6.894757293168 kPa) reported false accepts under glare. The current run, on the rebuilt dataset, reports none. The scenes and unit table differ between the runs and the cause of the change was not isolated, so the earlier false accepts are not evidence of a fix and glare remains a risk worth re-testing on more scenes.

## 4. Cross-implementation parity

| Check | Result | Where run |
| --- | --- | --- |
| `scripts/check_solver_parity.py` (Python rules vs Rust `pp`) | 1000 scenes, 1500 pumps, 0 mismatches (seed 4628501) | Linux (WSL Ubuntu 22.04) |
| `pytest -q python/tests` | 144 passed | Linux (WSL Ubuntu 22.04) |
| `ruff check python scripts` | Linux run flagged one finding (`subprocess.run` without `check`), fixed; passes on Windows after the fix, not re-run on Linux | Windows, Linux |
| `cargo build -p panelproof-scoring --bin pp` | built | Linux (WSL) |
| Smoke (16 steps: build, verify, export, API, reveal, attempts, idempotency, report) | 16 pass, 0 fail, 1 not run (web, needs `--web`) | Linux; Windows run covered the web step |

## 5. Human review

`results/human_audit_worksheet.csv` lists 50 tasks sampled across skills for a human reviewer. **No human has reviewed any task.** `results/human_audit_status.json` records zero reviewers and no agreement statistic. Until a person completes the worksheet, task answerability and ambiguity are validated only by the automated checks above.

## What this does not show

No model has been evaluated (all report outputs are DEMO ONLY). The generator and verifier share a repository, so verifier agreement shows internal consistency, not agreement with an independent reader. Docker, Compose and macOS paths were not run.
