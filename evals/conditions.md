# Evaluation conditions and metrics

This extends [`protocol.md`](protocol.md) (the proposed experiment) and [`runner.md`](runner.md) (how attempts are produced). It documents what `python -m panelproof.cli metrics` computes.

## Conditions

| Condition | Input | Purpose |
| --- | --- | --- |
| C0 | Question, public rules, response schema (no image) | Text-only prior; measures what can be answered without looking |
| C1 | C0 plus the task PNG | The actual evaluation |
| C3 | C0 plus the verifier's recovered readings (no image) | Reasoning ceiling given correct readings |

Metrics compare conditions on **matched tasks only**. Tasks missing a condition are counted and reported, not silently dropped. Grounding gain is C1 − C0 on the matched set.

## Measured runs need a freeze

With `--measured`, `metrics` requires a dataset freeze manifest and a recorded access approval whose selection hash matches (`require_freeze`), so a run cannot be quietly retargeted after results are seen. Without the flag the report is for development only. Before a measured run record the authorizing account, provider and model revision, selection hash, conditions, caps and the exact command.

## Reported quantities

- Attempted, completed, valid and correct counts, with both valid-only and all-attempt accuracy. Failures are typed (`parse_error`, `provider_error`, `timeout`).
- Accuracy by skill (R, C, M, X) and difficulty (easy, medium, hard).
- Pair metrics: semantic directional sensitivity, nuisance invariance, preserving both-correct.
- Worst-group accuracy and all-variants-correct.
- 95% intervals by cluster bootstrap over groups (1000 resamples, fixed seed), so siblings are resampled together.
- Latency (mean, p95), observed cost and cache-hit rate.
- With `--rust-pp`, every outcome is replayed through the independent Rust scorer and any disagreement is listed.

## Labels

Mock outputs from the offline adapter are labelled **DEMO ONLY** in the data and in every report. The committed [`docs/results/smoke_report_demo.md`](../docs/results/smoke_report_demo.md) shows the report format only (68 matched tasks over 8 groups); its numbers are not model performance.

## Not yet done

No live model has been run. No cost or latency figure here is a measurement of a real provider. Subgroups with few groups produce wide intervals that should be read as such.
