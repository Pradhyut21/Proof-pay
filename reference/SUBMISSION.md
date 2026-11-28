# Innodata Frontier AI Hackathon 2026

PanelProof is a Track 2 Visual Task Factory project. The public schedule lists **6 December 2026** as the submission date. The organizer's current event data allows solo entries and teams of up to four. [Official event](https://hack2skill.com/event/innodata/) · [Current event data](https://hack2skill.com/api/v1/event/innodata/event-details)

The public brief calls for reusable source and setup, inspectable samples with validation, findings on multimodal model strengths and weaknesses, and a technical demo that distinguishes correct from incorrect responses. The [submission checklist](../submission/DELIVERABLE.md) maps those outputs to the repository and records what remains pending.

## Participant resources

The participant guide lists Click, Zod, jsoncpp, verified base commits, and Harbor 0.25.x under **Track 1, Coding Task Factory**. **Track 2, Visual Task Factory** lets teams choose a practical visual problem and image family. PanelProof uses synthetic pump panels and submits its generation and evaluation pipeline, example tasks, validation, and measured model findings. [Participant guide](https://docs.google.com/document/d/1dk_C057AJFQsL5UzmNZ1YoQB7AWSml7go0NUrX-UrCM/edit)

The guide calls for standardized Docker execution and an end-to-end walkthrough video for both tracks. The [organizer deck template](https://docs.google.com/presentation/d/1fXZJ86GvJ-UnR4C7CkeWoTnzNqC7-gznV7efty8Su50/edit) provides the presentation structure. The [demo script](../submission/demo_script.md#organizer-deck) maps PanelProof evidence to its slides.

| Criterion | PanelProof evidence |
|---|---|
| Working implementation and repeatability, 25% | [Reproduction guide](../docs/reproducibility.md) and checked CLI/browser runs |
| Validity and validation evidence, 25% | [Task definitions](../docs/task_card.md), [automated validation](../docs/validation.md), and the pending [human review](../docs/human_audit.md) |
| Meaningful variation, 20% | [Dataset card](../docs/dataset_card.md) and [worked comparison](../README.md#one-question-three-panels) |
| Original approach and engineering judgment, 15% | [Source audit](../docs/source_audit.md), [matched evaluation design](../evals/conditions.md), and [evaluation evidence and gaps](../docs/evaluation_results.md) |
| Practical impact and communication, 15% | [Judge walkthrough](../submission/demo_script.md) and [scoring and reveal](../docs/api.md) |

## Registered dashboard checks

The public timeline and FAQ give **6 December 2026 at 11:59 PM IST**. The live event configuration gives a submission end time of **11:55 PM IST** on the same day. Check the registered dashboard and plan to submit before the earlier time. [Public timeline](https://hack2skill.com/event/innodata/?sectionid=6aedaccb6808a5c6d6fc4f6e) · [Current event data](https://hack2skill.com/api/v1/event/innodata/event-details)

- [ ] Confirm the selected challenge is **Track 2** and both members are on its registered roster. A two-person team meets the published size rule.
- [ ] Verify the submission cutoff, required Track 2 interface, upload formats and size limits in the registered dashboard.
- [ ] Verify the permitted model API access and usage limits before paid inference.
- [ ] Verify which interface, sample formats, and demo artifacts the portal accepts. Confirm whether the portal accepts a separate judge key.

The registered dashboard details remain pending in [#1 and #20](https://github.com/Pradhyut21/Panel_Proof/issues?q=is%3Aissue+submission).
