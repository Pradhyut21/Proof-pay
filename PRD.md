# PanelProof product requirements

**Innodata Frontier AI Hackathon 2026 · Track 2, Visual Task Factory**  
**Owners** Pradhyut (`Pradhyut21`) and Kishan (`kishansaaai`)  
**Submission deadline** 6 December 2026. Confirm the exact cutoff and submission format in the registered dashboard.

[GitHub backlog](https://github.com/Pradhyut21/Proof-pay/issues) · [Build roadmap](https://github.com/Pradhyut21/Proof-pay/issues/1) · [Official Track 2 brief](https://hack2skill.com/event/innodata/?sectionid=6aee108b9be15aea67016065)

## What we are building

PanelProof generates synthetic images of fictional water-pump control panels, questions that require reading those images, and independently checkable reference answers. It runs existing vision-language models on the tasks to measure where they misread gauges, confuse equipment, or apply a correct reading to the wrong rule. A judge can generate a fresh panel, answer a question, compare counterfactual variants, and inspect the pixels and calculations behind the score.

**Training ownership.** PanelProof has no model training or fine-tuning step. Kishan owns the generator, independent raster verifier, and audited dataset freeze. Pradhyut owns question and reference logic, independent Rust checking and scoring, and evaluation of existing models. Their coding-agent subscriptions are separate from the model API access used in experiments.

**First slice.** Render a clearly labeled pump with two linear dials and RUN/ALARM indicators. Ask one question, recover the required evidence independently from the PNG, agree on the answer in Python and Rust, and score a human or offline demo response. Extend to more layouts and skills once that slice is repeatable.

## Visual tasks and rules

The panel contains labeled inlet and outlet readings and visibly distinct RUN and ALARM indicators. Start with one pump and add twin-pump layouts to test equipment association. Vary positions, labels, display units, and themes while preserving readable, sufficient evidence. The benchmark uses fictional operating rules.

1. When RUN is off, the named pump is **STOPPED**.
2. When RUN is on, convert inlet and outlet pressure to kPa and compute **outlet minus inlet**. A difference **at least 300 kPa** means **NORMAL**, otherwise **LOW_PRESSURE**.
3. ALARM is expected to be on only in **LOW_PRESSURE**. A consistency question compares the visible ALARM state to that expectation.

| Skill | Example | Dataset target |
| --- | --- | --- |
| R · Reading | Read the named pump's inlet gauge in its displayed unit. | At least 100 |
| C · Conversion | Read an outlet gauge and convert its value to a requested unit. | At least 80 |
| M · Composition | Associate equipment, compute a pressure difference, or apply the public rule. | At least 150 |
| X · Consistency | Determine whether the visible ALARM agrees with the rule. | At least 100 |
| Counterfactuals | Move one needle across the threshold, or change only the theme. | At least 50 pairs |
| Missing evidence | Remove a necessary reading and score abstention as `INSUFFICIENT`. | 40 diagnostics in a separate set |

Use fixed-point integers in thousandths of a display unit. Start with kPa, bar and psi using the shared rational unit table. When normalizing to milli-kPa, round to nearest with ties away from zero. If the supported reading uncertainty spans a class boundary, reject the task. Use exact readable boundary fixtures to test the inclusive threshold. Generate public rule text from the executable rule definition. Keep labels, positions, and irrelevant appearance cues from predicting answers. Cross displayed ALARM with expected rule state and report cue association by skill.

Each semantic-flip pair changes one material fact and produces the expected answer change. A nuisance pair changes appearance while preserving the answer. A meaning-preserving unit conversion can exercise precision and association. Record the exact mutation and group privately. Missing-evidence examples must lack enough information for a unique main-benchmark answer.

## System and handoffs

| Layer | Requirements |
| --- | --- |
| Python 3.11 | Seeded CPU 2D rendering with Pillow, Pydantic contracts, question/reference generation, independent OpenCV raster verification, model adapters and evaluation runner. |
| Rust | Axum/Tokio/Serde with SQLx/SQLite for local API and job state. Independent typed rule engine, unit-aware scoring, and canonical SHA-256 manifests. |
| Web | Next.js and strict TypeScript, Tailwind/shadcn, and Prettier. Task Factory, Model Arena, Evidence Inspector, and Run Reports. |
| Tooling | Versioned schemas, shared golden cases, pinned lockfiles, CI, native Windows and Linux/WSL smoke commands, optional Compose. |

Use `python/src/panelproof/` for generation, questions, verification, export and adapters. Use `crates/{api,oracle,scoring}/` for Rust and `apps/web/` for the UI. Put shared schemas in `schemas/`, unit factors and goldens in `shared/`, benchmark settings in `configs/`, evaluation protocol in `evals/`, and release evidence in `docs/` and `submission/`. Use schema version `1.0.0` for the first contract. Agree the public/private record examples and `shared/golden/pump_rules.json` before duplicating types or implementing new rule families.

**Worker/API contract.** Rust owns DB writes and calls fixed Python subcommands using bounded argument lists and versioned JSON/JSONL. Validate artifacts and hashes before publication. Define health and capabilities, generation/evaluation jobs with polling, public task/image retrieval, human attempts, authorized local reveal, and run metrics/export. Publish the typed API fixture early so the frontend can start in parallel. Default to a local, loopback service with explicit origin, request, job and artifact limits.

**Visibility.** The public task has an opaque ID, image reference, question, public rules and response schema. A normal provider request carries the PNG bytes where applicable, question, rules, and response schema. Private records hold seed, lineage, split, reference answer, tolerance, evidence regions, verifier trace and hashes. Authorized local dev/sample reveal may expose supporting evidence. Keep frozen test answers, keys and seeds private.

## Dataset construction and validation

1. **Pilot.** Generate 20 dev base scenes and 30–50 questions. Keep pilot groups out of the frozen set. Start with coarse ticks and clean layouts. Compare full-image and readings-only performance if approved model access is available. Tune difficulty and validation before freeze.
2. **Independent verification.** Recover dials, visible units/labels and signal states from PNG pixels and public calibration. Derive the verdict from the recovered readings. The verifier input excludes renderer coordinates, masks, SVG and hidden truth. Compare its output to generator truth outside the verifier. Record uncertainty, rejection reasons and coverage.
3. **Regression checks.** Validate canvas bounds, overlap, legibility, unique answer, threshold margin, byte-identical regeneration, PNG metadata stripping, cue balance and variant integrity. Exercise independent fixtures with shifted needles, changed units/labels, wrong lamps, altered truth, missing evidence and unreliable views. Check Python/Rust agreement on shared goldens and 1,000 seeded scenes. Report actual pixel-verifier performance by difficulty, with one minor tick as the baseline reading tolerance where appropriate. Measure against the 95% moderate-perturbation agreement target and narrow supported families if necessary.
4. **Freeze.** Target 500 accepted answerable tasks and 40 separate diagnostics. Keep siblings, near-duplicates and layout lineage together. Start with approximately 20% dev and 80% frozen by group and report actual split counts. Save a hashed manifest and rejection ledger. Separate public PNGs/tasks, private answers and verifier traces. Prepare 30 inspectable examples and a separate judge key. Set up a stratified 50-task human audit and report how many were actually reviewed.
5. **Optional external check.** After verifying provenance, access and redistribution terms, use a small deterministic MeasureBench slice for single-instrument reading only. Record it separately from the synthetic multi-instrument results. [MeasureBench source](https://github.com/flageval-baai/MeasureBench) · [Dataset and license](https://huggingface.co/datasets/FlagEval/MeasureBench)

## Evaluation and judging evidence

Run the same selected tasks under **C0** text-only, **C1** full panel, and **C3** verified visible readings as text. C3 deliberately supplies readable values to measure rule reasoning; omit private records and the verdict. Add **C2** crops and **C4** panel plus readings when time permits. Compare semantic and nuisance pairs on the same groups.

Use strict structured answers and deterministic scoring for categories, sets and numeric/unit tolerances. Persist model/version, prompt version, selection hash, condition, status, latency and available usage or cost. Report attempted, valid, and correct counts; valid-only and all-attempt accuracy; provider and parse failures; per-skill and difficulty results; pair correctness, directional sensitivity, invariance, worst-group accuracy, and matched grounding gain (C1 minus C0). Include base-group intervals if supported and show actual cases with images, references and verifier traces.

Default to offline checks and clearly label mock runs **DEMO ONLY**. For measured runs, aim for three accessible multimodal models, record provider permissions and caps before live calls, and report what actually ran.

| Judging criterion | Evidence |
| --- | --- |
| Implementation and repeatability · 25% | Clean-checkout command from generation through deterministic score and report. |
| Validity and validation · 25% | Pixel evidence, solver agreement, corruption tests, rejection and audit records. |
| Meaningful variation · 20% | Multiple reasoning skills, semantic and nuisance variants, grouped split tests. |
| Originality and judgment · 15% | Explain multi-instrument reasoning with explicit rules, verify prior art, and document measured limitations. |
| Practical impact and demo · 15% | Explain why equipment association and reading errors matter, then show live scoring and evidence reveal. |

## Ownership and order

The backlog is split **10 issues and 43 estimated effort points each**. Begin with the build contract and source audit. Once the shared schema examples are available, build generation, questions, scoring and evaluation adapters in parallel.

| Stage | Pradhyut | Kishan | Exit evidence |
| --- | --- | --- | --- |
| Foundation | [#1 Contract and portal](https://github.com/Pradhyut21/Proof-pay/issues/1), [#4 Schemas](https://github.com/Pradhyut21/Proof-pay/issues/4) | [#2 Source audit](https://github.com/Pradhyut21/Proof-pay/issues/2), [#3 Scaffold](https://github.com/Pradhyut21/Proof-pay/issues/3) | Shared fixtures, compatible tools, local smoke entry point. |
| Pilot | [#6 Rules/questions](https://github.com/Pradhyut21/Proof-pay/issues/6), [#8 Rust rules/scoring](https://github.com/Pradhyut21/Proof-pay/issues/8), [#10 Pilot](https://github.com/Pradhyut21/Proof-pay/issues/10), [#12 Evaluation runner](https://github.com/Pradhyut21/Proof-pay/issues/12) | [#5 Renderer](https://github.com/Pradhyut21/Proof-pay/issues/5), [#7 Variants](https://github.com/Pradhyut21/Proof-pay/issues/7), [#9 Raster verifier](https://github.com/Pradhyut21/Proof-pay/issues/9) | Verified pilot, recorded failures, offline model fixture. |
| Freeze and integrate | [#14 Axum API](https://github.com/Pradhyut21/Proof-pay/issues/14), [#16 Evidence/Reports](https://github.com/Pradhyut21/Proof-pay/issues/16) | [#11 Dataset freeze](https://github.com/Pradhyut21/Proof-pay/issues/11), [#13 Conditions/metrics](https://github.com/Pradhyut21/Proof-pay/issues/13), [#15 Factory/Arena](https://github.com/Pradhyut21/Proof-pay/issues/15), [#17 Reproducibility](https://github.com/Pradhyut21/Proof-pay/issues/17) | Hashed test set, judge workflow, one-command reproducibility. |
| Report and release | [#18 Measured results](https://github.com/Pradhyut21/Proof-pay/issues/18), [#20 Package/demo](https://github.com/Pradhyut21/Proof-pay/issues/20) | [#19 Independent audit](https://github.com/Pradhyut21/Proof-pay/issues/19) | Traceable findings, audit, release package, rehearsed demo. |

**Suggested checkpoints.** 24–26 Nov for contract and setup, 27–29 Nov for the pilot, 30 Nov–1 Dec for freeze, 2–4 Dec for measured runs and integration, 5 Dec for the final audit and rehearsal. If time is short, keep the independent verifier, grouped dataset, score and demo working. Defer advanced scales, external data, C2/C4 and frontend polish.

## Release checklist

- [ ] Confirm the registered roster and portal specifics in #1. Hack2skill lists **3–4 participants**. If the registered team currently has two, resolve the third-participant requirement.
- [ ] Deliver runnable source and setup steps, samples and a separate review key, validation/test logs, report and figures, license notices, source commit, and artifact checksums.
- [ ] Rehearse a three-minute demo. Generate a new panel, answer it, compare a semantic and nuisance variant, reveal independent evidence, and show measured results or an explicitly labeled demo fixture.
- [ ] Audit package contents and recreate a sample from a clean checkout. Preserve exact commands, actual test outcomes, example paths, known gaps and the next handoff.
- [ ] Confirm the registered team’s submission format, cutoff and permitted model access. Use the portal’s confirmed requirements for the final upload.

[Kishan’s source audit](https://github.com/Pradhyut21/Proof-pay/issues/2) contains pinned entry points for MeasureBench, ETH gauge reader, CLEVR, DynaMath and VLMEvalKit. Use these as design references and verify permissions before reusing assets, models or code. [Official schedule and eligibility](https://hack2skill.com/event/innodata/)
