# Evaluation conditions and metrics

This extends [`protocol.md`](protocol.md) (the proposed experiment) and [`runner.md`](runner.md) (how attempts are produced). It documents what `python -m panelproof.cli metrics` computes.

## Conditions

| Condition | Input | Purpose |
| --- | --- | --- |
| C0 | Question, public rules, response schema (no image) | Text-only prior; measures what can be answered without looking |
| C1 | C0 plus the task PNG | The actual evaluation |
| C3 | C0 plus the verifier's recovered readings (no image) | Rule reasoning given recovered visible readings |

Metrics compare conditions on **matched tasks only**. Tasks missing a condition are counted and reported, not silently dropped. Grounding gain is C1 − C0 on the matched set.

## Measured runs need a freeze

Prepare the default balanced cohort from the privately seeded holdout before requesting model access. The command writes a new JSONL file outside the holdout and Git and prints the selection hash, scope, and aggregate count. The rows contain the public task fields. Keep the file local because its membership is derived from the private selection.

```sh
uv run --project python --python 3.11 --locked python -m panelproof.cli prepare-measured-cohort \
  --dataset /local/holdout --out /local/measurement/tasks.jsonl
```

The default includes frozen R, C, and M tasks and the complete manifest-committed balanced X slice for each chosen split. Use the printed `selected_count` as `--limit` in each C0, C1, and C3 preflight and run. Further truncating the JSONL may break matched coverage or X balance. The full holdout stays unchanged. To study the separate full X scope, use `--x-scope full` for both cohort preparation and measured reporting, and record `"x_scope": "full"` in the local approval. If X tasks are included, the measured report checks complete membership of the chosen X scope for every represented split. An explicitly approved selection may omit X, in which case its measured X count is zero.

Use `--measured --attempt-format contract` only with a privately seeded holdout built by the exporter. Supply its dataset directory via `--tasks`, one `--attempts` argument per run, and `--approval` pointing to the team’s local authorization record. Keep each attempt file alongside its original `run.json`. Each model must cover an identical nonempty cohort under C0, C1, and C3. The report checks the holdout's role and hashes and the model provenance. It re-reads the manifest-pinned public task list and PNGs, recovers visible readings locally, and verifies the exact prompts and image bytes recorded by the runner under each condition. It also checks the C3 observation digest independently. Public reproducibility builds, development and diagnostic tasks, and mock attempts are rejected. A partial cohort with skipped tasks or missing conditions can be inspected as a development report.

The authorization record includes `approved_by`, the holdout's `manifest_sha256`, the `selection_hash` from `panelproof.metrics.selection_hash(task_ids, conditions)`, and `models`, an array of objects with `provider`, `model_id`, and `model_revision`. Its `x_scope` defaults to `balanced`. This selection hash covers the approved unordered task IDs and conditions. The runner's separate `selected_task_ids_sha256` covers the ordered rows within each run. Include approved limits and exact run commands in the team's local lock record before requesting model inference.

The reporting gate validates artifacts after inference. Obtain authorization and commit to the selected task IDs and conditions before starting requests. A report assembled without `--measured` is labeled development or **DEMO ONLY**. The provider runner accepts C0, C1, and C3. C3 preflights the entire cohort by recovering readings directly from PNGs and uses only the visible observations described in [`runner.md`](runner.md).

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
