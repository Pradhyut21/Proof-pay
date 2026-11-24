# Judge audit (self-audit)

**Read this first.** The work plan asks for an audit by a fresh, independent session. This document was written by the same session that built most of the code, so it is a self-audit, not an independent one. It lists evidence the repository holds and where it falls short, so a real independent reviewer can start from it.

## Rubric matrix

| Area | Evidence in repo | Status |
| --- | --- | --- |
| Reproducible dataset | `./run.sh dataset`, `audit`; manifest hash recorded; audit rebuilds byte-identically | Verified on Windows and Linux paths used (below) |
| Leakage control | Group splits; zero cross-split seeds, groups, images; public files carry no private fields (audited) | Verified by `audit-dataset` |
| Independent solver | Rust oracle vs Python rules, 1000 scenes, 0 mismatches | Verified (WSL Linux) |
| Independent reading | Raster verifier uses PNG only | Verified internally; same repository, not an outside reader |
| Perturbation robustness | `docs/results/perturbation.json` | **Weak**: below 95% agreement on 6 of 8 perturbations; no false accepts |
| Shortcut resistance | Answer-class audit | **Weak** for X tasks (28 pp ALARM shift); state tasks pass (1.3 pp) |
| Human validation | 50-task worksheet | **Not done**: zero reviewers |
| Model results | Offline mock only, labelled DEMO ONLY | **Not done**: no live model run |
| API and app | Smoke steps and Playwright flow | Verified locally; no hosted deployment |
| Platform coverage | Windows (native Python/Node, Rust via WSL), Linux (WSL) | macOS, native Windows Rust, Docker/Compose **not run** |
| Licensing | `LICENSE` is an MIT placeholder; font license not independently verified | **Open** |

## Five ranked fixes

1. **Human review of the worksheet.** Without it, answerability is only machine-checked. Two reviewers and an agreement statistic.
2. **Remove the X-task ALARM shortcut.** Rebalance or add ALARM-neutral X tasks so the answer class does not shift by 28 pp with the lamp state.
3. **Harden or scope the verifier.** Either handle small rotation, scale and noise, or state that acceptance is limited to clean renders and test on more than 30 scenes.
4. **Run a live model.** Authorized access, frozen selection, C0/C1/C3, with the measured-run guard.
5. **Add layout families.** Two families cannot support claims about general panel reading; the held-out theme tests style only.

## Interim components that stand in for missing parts

- Task Factory job runner in the web layer (the API has no job routes).
- Demo adapter for the runner's mock provider.
- Factory `model_attempts` fixture format converted by `metrics --attempt-format`.

## Claims deliberately not made

No statement is made about model accuracy, about Devpost or paper results, or about real instruments.
