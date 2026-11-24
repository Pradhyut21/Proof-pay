# Evaluation evidence and current status

PanelProof measures how a vision-language model reads fictional pump control panels and applies public rules. The repository has reproducibility, verifier, and scorer evidence. Live model findings remain pending.

## Development pilot

The same 50 development tasks passed preflight under C0, C1, and C3. The sample includes 10 reading, 10 conversion, 10 multi-instrument, and 20 indicator-consistency tasks from 21 groups. The C3 preflight recovered visible readings for 33 distinct PNGs. These checks did not call a provider. [Conditions and reporting](../evals/conditions.md) · [Runner instructions](../evals/runner.md)

| Evidence | What it covers | Status |
| --- | --- | --- |
| Clean raster pilot | Independent recovery compared with generator truth | 19 of 20 scenes recovered, exact agreement on all 19 recoveries. [Pilot report](results/integration_pilot.md) |
| Rule implementation | Independent Python and Rust readings conversion and rule outcomes | 1,000 seeded scenes, 1,500 pumps, zero mismatches. [Validation](validation.md#4-cross-implementation-parity) |
| Holdout audit | Group and seed isolation, pair validity, and the marginal ALARM cue | 696 answerable tasks, 282 valid question pairs, zero cross-split groups, images or seeds. [Dataset card](dataset_card.md#current-private-holdout) |
| Browser report | 71 matched tasks across 8 groups and 213 fixture attempt rows | Local scoring and report export verified. **DEMO ONLY**. [Browser and CI checks](https://github.com/Pradhyut21/Proof-pay/pull/25) |
| Human answerability | Two independent reviews of a prepared 50-task sample | 0 of 50 judged. [Review procedure](human_audit.md) |
| Live model findings | Matched model runs and case analysis | Awaiting organizer model access and approved usage. [Evaluation issue](https://github.com/Pradhyut21/Proof-pay/issues/18) |

## Scope

- The current simulations cover one pressure-rule family, two layouts, and four themes. The held-out theme tests style changes.
- Raster verification targets clean renders. The historical perturbation study had zero recoveries under 1° rotation or sigma-3 noise on 30 scenes per setting. [Perturbation evidence](validation.md#3-raster-verifier-under-perturbation)
- The balanced X slice controls the marginal ALARM shortcut. The full held-out dataset remains available for analysis with its separate shortcut audit.
- Model error analysis requires actual outputs. For an approved run, record matched sample counts, accuracies with both denominators, failures and uncertainty, and inspectable cases tied to the question, image, and reference. [Frozen protocol](../evals/protocol.md) · [Submission checklist](../submission/DELIVERABLE.md)
