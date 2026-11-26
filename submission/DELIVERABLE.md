# PanelProof submission checklist

PanelProof is a Track 2 visual benchmark for reading and reasoning over fictional pump panels. Existing vision-language models are evaluated on synthetic tasks from the factory. See the [benchmark contract](../reference/CONTRACT.md) and [public submission requirements](../reference/SUBMISSION.md).

## Artifact checklist

| Submission artifact | Review it here | Release status |
| --- | --- | --- |
| Reusable generation and evaluation source, setup, and commands | [README](../README.md) · [Reproduction guide](../docs/reproducibility.md) · [Architecture](../docs/architecture.md) | The source candidate reproduced byte-for-byte and passed the extracted Windows core smoke. Record the exact commit and archive SHA-256 for the final upload. |
| Inspectable sample images and public questions | [Public demo bundle](https://github.com/Pradhyut21/Proof-pay/tree/main/data/demo/public) · [Worked example](../README.md#one-question-three-panels) · [Task card](../docs/task_card.md) | The local review package has six verified sample tasks and three comparison pairs. The companion archive binds the six judge answers to the sample manifest. |
| Validation and tests | [Dataset card](../docs/dataset_card.md) · [Validation](../docs/validation.md) · [CI](https://github.com/Pradhyut21/Proof-pay/actions/runs/45564997958) · [Platform checks](https://github.com/Pradhyut21/Proof-pay/actions/runs/45564997988) | Automated evidence and a blinded 50-task development review pack are available. Both reviewers' worksheets and agreement are pending. |
| Model strengths and weaknesses | [Evaluation evidence](../docs/evaluation_results.md) · [Protocol](../evals/protocol.md) · [Research issue #18](https://github.com/Pradhyut21/Proof-pay/issues/18) | C0, C1, and C3 preflight passed on the same 50 v0.4 development tasks. C3 recovered 33 distinct images. The live pilot plans 150 initial requests per model before retries. Provider calls and measured findings remain pending. |
| Technical explanation, deck, and walkthrough video | [Architecture](../docs/architecture.md) · [Walkthrough script and deck map](demo_script.md) · [Organizer deck template](https://docs.google.com/presentation/d/1fXZJ86GvJ-UnR4C7CkeWoTnzNqC7-gznV7efty8Su50/edit) | Six automated browser scenarios passed. Fill the deck with the registered team details and actual evidence, then record an end-to-end walkthrough. |
| Provenance and redistribution | [MIT code license](../LICENSE) · [Third-party notices](../THIRD_PARTY_NOTICES.md) · [Dataset sources](../docs/dataset_sources.md) | Code and bundled font provenance documented. Generated dataset release terms need a team decision. |

## Record the final handoff

- [ ] Source commit, environment, smoke command and result, file names, and SHA-256 checksums.
- [ ] Sample IDs, sample images and public questions, and separate judge key for approved samples.
- [ ] Measured run IDs, model revisions, selection and manifest hashes, failures, and sample counts when available.
- [ ] Completed human review summary, organizer deck, and recorded end-to-end walkthrough showing generation, validation, and scoring.
- [ ] Archive inspection for private holdout answers, credentials, and redistribution permissions.

## Verified application baseline

The v0.4 engineering baseline is merge commit `1b42239f1f9938fca84960b0724e3f3f2d9d1f18`. Its extracted source ZIP passed 16 native Windows core checks, including a locked Rust build and Axum API scoring. The optional web check was run separately on the matching source tree. A fresh production build passed six Windows Edge scenarios in 118.98 seconds of test wall time, covering generation, scoring, counterfactual comparisons, reveal, refusal, report export, and job expiry. The browser report used 71 matched offline tasks labeled **DEMO ONLY**. [v0.4 merge evidence](https://github.com/Pradhyut21/Proof-pay/pull/28)

Linux CI passed the production web build and full pipeline smoke. The separate platform workflow passed Compose build/startup and macOS core checks. [Linux CI](https://github.com/Pradhyut21/Proof-pay/actions/runs/45564997958) · [Platform workflow](https://github.com/Pradhyut21/Proof-pay/actions/runs/45564997988)

The existing Compose check exercises the web and API against the demo bundle. The participant guide calls for standardized Docker execution. Verify a fresh generation, validation, scoring, and report run in Docker before the final handoff. [Participant guide](https://docs.google.com/document/d/1dk_C057AJFQsL5UzmNZ1YoQB7AWSml7go0NUrX-UrCM/edit)

## Build the source ZIP

From the repository root, run the standard-library release tool after reviewing and committing the intended release source. The parent of the output directory should exist.

```sh
python scripts/release.py --rev HEAD --out-dir ../panelproof-source-release
```

The tool resolves the revision to an exact commit and reads the matching Git blobs. It writes the source ZIP, its SHA-256 sidecar, and a `manifest.json` in the output directory. The archive also contains `panelproof/submission/manifest.json` with the source SHA and each included file's content hash. Archive member order, timestamps, and modes are fixed for repeat runs with the same Python and compression tooling.

The source allowlist covers code, configuration, documentation, and specific public figures and evidence summaries. Prepare sample bundles, new raw logs, measured outputs, and the judge key as separate artifacts. Inspect the ZIP contents and confirm the SHA-256 before handing it off.

For an extracted source ZIP, bootstrap the dependencies and generate a local development bundle before starting the API or Compose. [Source-only quickstart](../docs/reproducibility.md#start-from-an-extracted-source-zip)

## Verify the registered portal

- [ ] Confirm that Track 2 is selected and both members appear on the registered roster. A two-person team meets the [published size rule](../reference/SUBMISSION.md#registered-dashboard-checks).
- [ ] Confirm the exact cutoff and timezone for the 6 December 2026 submission deadline, required Track 2 fields and interfaces, upload formats and size limits, and whether a separate judge key can be submitted. The [public schedule and event configuration](../reference/SUBMISSION.md#registered-dashboard-checks) show different cutoff times. Plan to submit before the earlier time.
- [ ] Record the final artifact names, hashes, command logs, and outstanding evidence gaps. Have a registered team member perform the portal submission after review.

[Official event](https://hack2skill.com/event/innodata/) · [Submission issue #20](https://github.com/Pradhyut21/Proof-pay/issues/20)
