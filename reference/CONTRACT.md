# PanelProof build contract

PanelProof evaluates whether a vision-language model can read gauges, associate them with the correct pump, apply explicit rules, and respond to meaningful visual changes. A seeded simulator produces synthetic evaluation tasks. The reference answer comes from deterministic code and is checked with a second Rust implementation and independent raster recovery. Model training and fine-tuning are outside this project.

## Components

| Component | Responsibility |
|---|---|
| Python 3.11, Pydantic, Pillow, OpenCV | 2D generation, questions, raster validation and model providers |
| Rust, Axum, Tokio, SQLx, SQLite | Local API and job state, independent rule checks, scoring and SHA-256 manifests |
| Next.js, TypeScript, Tailwind, shadcn/ui, Prettier | Task Factory, Model Arena, Evidence Inspector and Reports |
| Shared JSON Schema | Versioned scene, public task, private task, attempt and run records |

The first working slice uses two linear dial gauges and labeled RUN/ALARM indicators per pump. Keep setup suitable for an 8 GB Windows laptop with native PowerShell, Linux/WSL and optional Compose entry points.

## Rules and data

- A pressure reading is a fixed-point integer in thousandths of its display unit. Use the rational factors in `shared/units.json` to normalize to milli-kPa, rounded to nearest with ties away from zero.
- For a selected pump, RUN off means STOPPED. With RUN on, an operating-state question states its threshold and input. The pressure-difference rule compares outlet minus inlet with 300 kPa. The v0.4 inlet-floor rule compares inlet with 150 kPa. A value at or above the threshold gives NORMAL. A smaller value gives LOW_PRESSURE. Consistency questions use the pressure-difference rule and expect ALARM exactly in LOW_PRESSURE.
- A scene includes a schema version, deterministic seed, base scene ID, layout and style families, and labeled pump readings. Public task records contain an opaque ID, relative image path, question, public rules and response schema. Provider requests carry only permitted image bytes, question, public rules and response schema.
- Private task records hold lineage, split, reference answer, tolerance, image hash and validation trace. Use tagged category, numeric/unit, and set answers. Store test answers separately from public data and authorized demo evidence. Freeze files with SHA-256 and deterministic serialization.
- Use one group for base scenes and their variants. Keep related layout lineage on one side of the split. Log validation failures, distinguish provider errors from wrong answers, and report both valid-only and all-attempt accuracy.

## Verification and handoffs

The Python raster verifier takes PNG pixels and public calibration/geometry conventions. It recovers readings and rule evidence from the visible panel. Hidden scene, masks, SVG and renderer coordinates are available only to the comparison step. Ambiguous or unsupported readings and unverifiable variants stay outside the accepted set.

Python and Rust use independently written rule code and the shared golden files. Workers exchange bounded, versioned JSON/JSONL using fixed command arguments. The Axum service owns SQLite writes, serves the public task projection and allows evidence reveal only for authorized local development/sample tasks.

Run a dev pilot of 20 independent base scenes and 30–50 questions before freeze. Build toward 500 accepted answerable tasks plus 40 separate missing-evidence diagnostics. Target R 100, C 80, M 150, X 100 and at least 50 counterfactual pairs. Report actual counts, rejected cases and shortfalls. Run C0 text-only, C1 full image and C3 verified visible readings first. Compare only matched samples and keep mock results labeled.

Kishan owns the synthetic generator ([#5](https://github.com/Pradhyut21/Proof-pay/issues/5)), raster verification ([#9](https://github.com/Pradhyut21/Proof-pay/issues/9)) and dataset freeze ([#11](https://github.com/Pradhyut21/Proof-pay/issues/11)). Pradhyut owns the questions and references ([#6](https://github.com/Pradhyut21/Proof-pay/issues/6)), pilot coordination ([#10](https://github.com/Pradhyut21/Proof-pay/issues/10)), runner ([#12](https://github.com/Pradhyut21/Proof-pay/issues/12)) and measured findings ([#18](https://github.com/Pradhyut21/Proof-pay/issues/18)). Coding-agent subscriptions and evaluation model API access are separate dependencies.
