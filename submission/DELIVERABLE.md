# PanelProof submission checklist

PanelProof is a Track 2 visual benchmark for reading and reasoning over fictional pump panels. Existing vision-language models are evaluated on synthetic tasks from the factory. See the [benchmark contract](../reference/CONTRACT.md) and [public submission requirements](../reference/SUBMISSION.md).

## Prepare the artifacts

- [ ] Record the commit SHA, environment, and a successful clean-checkout smoke command for the complete pipeline. [Reproducibility #17](https://github.com/Pradhyut21/Proof-pay/issues/17)
- [ ] Provide inspectable generated tasks with image and question files, plus a separate judge key for the approved samples.
- [ ] Include generator yield, rejection counts, independent raster verification evidence, rule/scoring validation, and controlled semantic and nuisance examples.
- [ ] Record which frozen model experiments actually ran. Link the measured results, failures, sample counts, and limitations. Label any demo scores **DEMO ONLY**. [Research report #18](https://github.com/Pradhyut21/Proof-pay/issues/18)
- [ ] Verify source attribution, dependency licenses, and authorization to redistribute any included asset. Inspect the final bundle for private frozen truths, credentials, and unreviewed third-party material.
- [ ] Rehearse and time the [three-minute demo](demo_script.md). [Independent audit #19](https://github.com/Pradhyut21/Proof-pay/issues/19)

## Build the source ZIP

From the repository root, run the standard-library release tool after reviewing and committing the intended release source. The parent of the output directory should exist.

```sh
python scripts/release.py --rev HEAD --out-dir ../panelproof-source-release
```

The tool resolves the revision to an exact commit and reads the matching Git blobs. It writes the source ZIP, its SHA-256 sidecar, and a `manifest.json` in the output directory. The archive also contains `panelproof/submission/manifest.json` with the source SHA and each included file's content hash. Archive member order, timestamps, and modes are fixed for repeat runs with the same Python and compression tooling.

The source allowlist covers code, scripts, project configuration, and documentation. Prepare approved samples, validation logs, measured outputs, the demo, and the judge key as separate artifacts. Inspect the ZIP contents and confirm the SHA-256 before handing it off.

## Verify the registered portal

- [ ] Confirm the registered roster and team eligibility. The public event lists 3–4 people per registered team.
- [ ] Confirm the exact cutoff and timezone for the 6 December 2026 submission deadline, required Track 2 fields and interfaces, upload formats and size limits, and whether a separate judge key can be submitted.
- [ ] Record the final artifact names, hashes, command logs, and outstanding evidence gaps. Have a registered team member perform the portal submission after review.

[Official event](https://hack2skill.com/event/innodata/) · [Submission issue #20](https://github.com/Pradhyut21/Proof-pay/issues/20)
