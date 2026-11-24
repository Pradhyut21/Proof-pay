# PanelProof submission checklist

PanelProof is a Track 2 visual benchmark for reading and reasoning over fictional pump panels. Existing vision-language models are evaluated on synthetic tasks from the factory. See the [benchmark contract](../reference/CONTRACT.md) and [public submission requirements](../reference/SUBMISSION.md).

## Artifact checklist

| Submission artifact | Review it here | Release status |
| --- | --- | --- |
| Reusable generation and evaluation source, setup, and commands | [README](../README.md) · [Reproduction guide](../docs/reproducibility.md) · [Architecture](../docs/architecture.md) | Runnable offline. Pin the final commit and archive checksum after the upload format is confirmed. |
| Inspectable sample images and public questions | [Public demo bundle](https://github.com/Pradhyut21/Proof-pay/tree/main/data/demo/public) · [Worked example](../README.md#one-question-three-panels) · [Task card](../docs/task_card.md) | Public examples available. Keep approved judge answers in a separate artifact for the registered review flow. |
| Validation and tests | [Dataset card](../docs/dataset_card.md) · [Validation](../docs/validation.md) · [CI](https://github.com/Pradhyut21/Proof-pay/actions/runs/45449233021) · [Platform checks](https://github.com/Pradhyut21/Proof-pay/actions/runs/45449232901) | Automated evidence available. Two human reviews and agreement remain pending. |
| Model strengths and weaknesses | [Evaluation evidence](../docs/evaluation_results.md) · [Protocol](../evals/protocol.md) · [Research issue #18](https://github.com/Pradhyut21/Proof-pay/issues/18) | Matched preflight complete. Authorized provider runs and measured findings remain pending. Label mock evidence **DEMO ONLY**. |
| Technical explanation and scoring demo | [Architecture](../docs/architecture.md) · [Three-minute script](demo_script.md) · [Browser rehearsal](https://github.com/Pradhyut21/Proof-pay/pull/25) | Six automated browser scenarios passed. The live three-minute presentation remains to be timed. |
| Provenance and redistribution | [MIT code license](../LICENSE) · [Third-party notices](../THIRD_PARTY_NOTICES.md) · [Dataset sources](../docs/dataset_sources.md) | Code and bundled font provenance documented. Generated dataset release terms need a team decision. |

## Record the final handoff

- [ ] Source commit, environment, smoke command and result, file names, and SHA-256 checksums.
- [ ] Sample IDs, sample images and public questions, and separate judge key for approved samples.
- [ ] Measured run IDs, model revisions, selection and manifest hashes, failures, and sample counts when available.
- [ ] Completed human review summary and timed demo or recorded demo permitted by the portal.
- [ ] Archive inspection for private holdout answers, credentials, and redistribution permissions.

## Verified application baseline

The application baseline is source commit `15cec4261fcdb08e61066c820cae46e534a39dc7`, merged into `main` as `57b3291f9bd9974736db74f91b03af14c9c78f8d`. The native Windows Edge run passed all six browser scenarios in 63.7 seconds wall time. The production build and 21 web tests passed. The automated suite covers generation, scoring, both counterfactuals, authorized reveal, refusal, job expiry, and report export. The fixture report covered 71 matched tasks from a local reproducibility build. [PR verification record](https://github.com/Pradhyut21/Proof-pay/pull/25)

Linux CI passed the production web build and full pipeline smoke. The separate platform workflow passed Compose build/startup and macOS core checks. Pin the actual submission commit and the generated ZIP's checksum before uploading. [Linux CI](https://github.com/Pradhyut21/Proof-pay/actions/runs/45449233021) · [Platform workflow](https://github.com/Pradhyut21/Proof-pay/actions/runs/45449232901)

## Build the source ZIP

From the repository root, run the standard-library release tool after reviewing and committing the intended release source. The parent of the output directory should exist.

```sh
python scripts/release.py --rev HEAD --out-dir ../panelproof-source-release
```

The tool resolves the revision to an exact commit and reads the matching Git blobs. It writes the source ZIP, its SHA-256 sidecar, and a `manifest.json` in the output directory. The archive also contains `panelproof/submission/manifest.json` with the source SHA and each included file's content hash. Archive member order, timestamps, and modes are fixed for repeat runs with the same Python and compression tooling.

The source allowlist covers code, configuration, documentation, and specific public figures and evidence summaries. Prepare sample bundles, new raw logs, measured outputs, and the judge key as separate artifacts. Inspect the ZIP contents and confirm the SHA-256 before handing it off.

For an extracted source ZIP, bootstrap the dependencies and generate a local development bundle before starting the API or Compose. [Source-only quickstart](../docs/reproducibility.md#start-from-an-extracted-source-zip)

## Verify the registered portal

- [ ] Confirm the registered roster and team eligibility. The public event lists 3–4 people per registered team.
- [ ] Confirm the exact cutoff and timezone for the 6 December 2026 submission deadline, required Track 2 fields and interfaces, upload formats and size limits, and whether a separate judge key can be submitted.
- [ ] Record the final artifact names, hashes, command logs, and outstanding evidence gaps. Have a registered team member perform the portal submission after review.

[Official event](https://hack2skill.com/event/innodata/) · [Submission issue #20](https://github.com/Pradhyut21/Proof-pay/issues/20)
