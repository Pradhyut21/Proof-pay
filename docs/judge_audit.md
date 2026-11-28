# Judge audit

The historical self-audit follows the fresh source review and records the baseline that prompted the fixes.

## Fresh source review

A separate coding-agent session reviewed the readiness changes using the PRD rubric. Its source review covered reproducibility, task validity, variation, prior art and the demo flow. It used the repository source and documentation. The reviewers of benchmark images are tracked separately in the [human audit](human_audit.md).

| Finding | Follow-up |
| --- | --- |
| Exact X task IDs and per-cell counts expose information about holdout answers | The selector writes exact metadata under `private/`. The manifest uses a commitment and the [dataset card](dataset_card.md#current-private-holdout) publishes aggregates. |
| Reviewer instructions gave decimals for prompts that require integer thousandths | The [blinded pack](human_audit.md) now uses the task's integer units. |
| The source archive omitted files required by Compose and the web app | The release allowlist includes the Dockerfiles and required web files. The [quickstart](../README.md#quickstart) documents local regeneration of the demo bundle. |
| Measured results accepted incomplete cohorts or input changes under the same task IDs | The measured gate requires an exact matched C0/C1/C3 cohort and verifies each run's prompt and image commitments against the approved holdout. [Evaluation conditions](../evals/conditions.md#measured-runs-need-a-freeze) |
| A change in display tolerance suppressed preserving-pair invariance for identical answers | Pair invariance compares values and units. Each task's correctness still uses its own tolerance. |

The v0.4 benchmark includes three layouts and two operating-state rules. The web Inspector and Run Reports shipped with a passing six-scenario browser rehearsal. The team has recorded the 2:55 walkthrough. Live-model findings and human judgments remain pending. [Judge console changes](https://github.com/Pradhyut21/Panel_Proof/pull/25) · [Current evidence status](evaluation_results.md)

## Historical rubric matrix

| Area | Evidence in repo | Status |
| --- | --- | --- |
| Reproducible dataset | `./run.sh dataset`, `audit`; manifest hash recorded; audit rebuilds byte-identically | Verified on Windows and Linux paths used (below) |
| Leakage control | Group splits; zero cross-split seeds, groups, images; public files carry no private fields (audited) | Verified by `audit-dataset` |
| Independent solver | Rust oracle vs Python rules, 1000 scenes, 0 mismatches | Verified (WSL Linux) |
| Independent reading | Raster verifier uses PNG only | Verified internally; same repository, not an outside reader |
| Perturbation robustness | `docs/results/perturbation.json` | Clean-render scope. Rotation and noise yielded 0 recoveries in the 30-scene study; no false accepts were observed |
| Shortcut resistance | Answer-class audit | **Weak** for X tasks (28 pp ALARM shift); state tasks pass (1.3 pp) |
| Human validation | 50-task worksheet | **Not done**: zero reviewers |
| Model results | Offline mock only, labelled DEMO ONLY | **Not done**: no live model run |
| API and app | Smoke steps and Playwright flow | Verified locally; no hosted deployment |
| Platform coverage | Native Windows Python, Node and Rust; Linux CI | [Platform workflow](../.github/workflows/platform-checks.yml) records macOS core checks and Compose build/startup |
| Licensing | Code under existing MIT file; bundled Aileron identified and publisher terms recorded | Generated dataset terms remain a team decision |

## Historical ranked fixes

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
