# Architecture

PanelProof has three layers that meet only at the shared contract ([`reference/CONTRACT.md`](../reference/CONTRACT.md), schemas in `schemas/`).

```
configs/*.yaml ──► Python factory ──► dataset bundle ──► Rust API ──► Next.js web app
 (seeded)          generate, render,   public/tasks.jsonl   Axum + SQLite   Task Factory, Arena,
                   verify, export      private/tasks.jsonl  reveal/attempts  judge flow
                          │            images/*.png                 ▲
                          └─ independent raster verifier            │
                                                    Rust oracle + scorer (pp)
```

## Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| Scene and rules | `python/src/panelproof/{scene,rules,rule_bridge,units}.py` | Seeded fictional panels; RUN/ALARM/pressure rules; fixed-point milli units with ties-away rounding from `shared/units.json` |
| Renderer | `render.py` | Draws a scene to PNG and emits evidence boxes. The expanded generator has three layout families and four themes. |
| Independent verifier | `verify.py`, `validate.py` | Recovers readings from the PNG using raster analysis only (no scene data) and compares them to the scene truth |
| Counterfactuals | `mutations.py` | Semantic-flip, answer-preserving (unit conversion), nuisance and missing-evidence siblings |
| Questions | `questions.py`, `question_bridge.py` | R, C, M, X task builders and the public/private split of each question |
| Export | `export.py`, `factory.py` | Contract bundle, split assignment by group, deterministic manifest hash |
| Metrics | `metrics.py`, `contract_attempts.py` | Matched C0/C1/C3 conditions, cluster bootstrap, parity with the Rust scorer |
| Oracle and scoring | `crates/{oracle,scoring}` | Independent Rust solver and the `pp` scorer |
| API | `crates/api` | Public task projection, token-protected reveal, idempotent attempts |
| Web | `apps/web` | Same-origin API proxy, Task Factory, Arena, Evidence Inspector and Run Reports |

## Trust boundaries

- Public records carry only `task_id`, `image_path`, `question`, `public_rules` and `response_schema`. Seeds, answers and evidence boxes live under `private/`.
- The reveal token is read from `PANELPROOF_REVEAL_TOKEN` by the Next.js server (`apps/web/lib/server/config.ts`) and by the API. It is never sent to client code.
- Task Factory jobs run on the Next.js server (`apps/web/lib/server/jobs.ts`) and shell out to `panelproof-cli`. This is an interim runner (see *Known gaps*).
- The Inspector reads the task's manifest-pinned raster data after the Axum reveal succeeds for the same demo task or active Factory job. Its response contains the reference and the displayed measurements. Run Reports reads a server-selected directory of aggregate reports and exports an allowlisted projection.

## Extending

- **New instrument or rule.** Add the instrument to `scene.py` and `render.py`, extend `rules.py` and the Rust oracle together, and add a case to `scripts/check_solver_parity.py`. The parity script compares both implementations on 1000 seeded scenes.
- **New layout family or theme.** Extend the [expanded generator configuration](../configs/generator-expanded.yaml) and verify the geometry with the independent reader. Groups with the configured held-out theme are assigned to the frozen side.
- **New model adapter.** Add a provider in `python/src/panelproof/adapters.py` and an entry in `configs/models.yaml`. Live runs need `--allow-live`, a positive cost cap and an authorizing account; see [`evals/runner.md`](../evals/runner.md).

## Known gaps

- The API has no job routes, so the Task Factory runner lives in the web layer.
- The factory writes model attempts in its own fixture format that `metrics --attempt-format` converts; the shared run format is `python -m panelproof.evaluate`.
- The v0.2 holdout covers two layout families. The expanded v0.3 reproducibility build adds side-by-side pumps with stacked dials. The evaluation covers one pressure-rule family and clean synthetic renders.
