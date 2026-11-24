# Independent integration pilot

The integration review generated 20 actual panel scenes with the public development namespace and the committed renderer configuration. The PNG verifier independently recovered 19 scenes. All 19 matched the reference exactly at the displayed ticks. One scene was rejected with `INLET:numerals_unreadable`. Recovery was 95% on this clean-render pilot, with no disagreements among recovered scenes.

| Check | Actual result |
| --- | --- |
| New scenes rendered | 20 |
| Scenes independently recovered | 19 |
| Exact tick agreement among recovered scenes | 19 of 19 |
| Rejected scenes | 1 unreadable inlet numeral |
| Generation manifest SHA-256 | `856b9ae6b949e2852f7d8bafd4764af11fc9372968f9272a4ebed3b111d4aaa3` |

The measurement covers the clean synthetic layouts available in the renderer. Rotation, scaling and noise remain separate from this pilot. Human review and provider-model evaluation require separate evidence. [Historical perturbation results](perturbation.json) · [Dataset card](../dataset_card.md)
