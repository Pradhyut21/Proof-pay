# PanelProof submission handoff

**TXET** · KM Pradhyut and Sai Kishan · Innodata AI Hackathon, Track 2, Visual Task Factory.

## What judges can inspect

| Artifact | Where to find it | Status |
| --- | --- | --- |
| Runnable source and setup | [README](../README.md#quickstart) · [Architecture](../docs/architecture.md) · [Reproduction guide](../docs/reproducibility.md) | Source and offline reproduction available. |
| Sample tasks | [Public demo questions](../data/demo/public/tasks.jsonl) · [Rendered sample grid](../data/samples/contact_sheet.png) · [Worked pair](../README.md#one-question-three-panels) | Public development samples. The separate judge key is a team handoff artifact. |
| Validation evidence | [Validation](../docs/validation.md) · [Dataset card](../docs/dataset_card.md) · [Evaluation status](../docs/evaluation_results.md) | Automated evidence available. Independent human review is pending. |
| Deck and walkthrough | [Video chapter guide](demo_script.md) · [Organizer requirements](../reference/SUBMISSION.md) | The 15-slide deck and 2:55 recording are complete. The team will supply the hosted video link. |
| Model findings | [Evaluation status](../docs/evaluation_results.md) · [Protocol](../evals/protocol.md) · [Issue #18](https://github.com/Pradhyut21/Panel_Proof/issues/18) | The matched 50-task development preflight passed for C0, C1, and C3. Live results are pending authorized model access. The recorded report uses **DEMO ONLY** fixtures. |
| Licensing and provenance | [MIT code license](../LICENSE) · [Third-party notices](../THIRD_PARTY_NOTICES.md) · [Dataset sources](../docs/dataset_sources.md) | Source and dependency credits are documented. Terms for a separate generated dataset release are pending. |

## Reproduce and package

Run `./run.sh reproduce` or `.\run.ps1 reproduce` for the offline generation-to-report path. Build the source ZIP from a committed revision.

```sh
python scripts/release.py --rev HEAD --out-dir ../panelproof-source-release
```

The command produces a source ZIP, a SHA-256 sidecar, and a manifest. The ZIP contains runnable code, configuration, documentation, and selected public evidence. Keep the review key and any separately approved measured artifacts in the team handoff. Use the [source ZIP setup](../docs/reproducibility.md#start-from-an-extracted-source-zip) to generate a local development bundle from the extracted archive.

## Verified baseline

The v0.4 engineering baseline `1b42239` passed 16 native Windows core checks and six Windows Edge scenarios covering generation, scoring, counterfactual comparisons, evidence reveal, report export, and job expiry. The Linux pipeline, macOS core, and Compose preview checks also passed. Compose serves the offline demo bundle. The native quickstart exercises new Task Factory generation. [Merged baseline](https://github.com/Pradhyut21/Panel_Proof/pull/28) · [Linux CI](https://github.com/Pradhyut21/Panel_Proof/actions/runs/45564997958) · [Platform workflow](https://github.com/Pradhyut21/Panel_Proof/actions/runs/45564997988)

## Registered portal

- Confirm both team members appear under Track 2 and verify the exact cutoff, required fields, and accepted artifact formats in the registered dashboard.
- Add the hosted walkthrough URL to the editable deck and confirm whether the portal accepts a separate judge key.
- Upload the approved artifacts and record final filenames and checksums. Track the remaining steps in [submission issue #20](https://github.com/Pradhyut21/Panel_Proof/issues/20).

[Organizer requirements](../reference/SUBMISSION.md#registered-dashboard-checks)
