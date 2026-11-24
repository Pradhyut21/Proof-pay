# Three-minute PanelProof demo

Before rehearsing, record the verified release SHA and keep its source manifest beside the browser. Use `judge-rehearsal` as the Task Factory seed with two panels. The checked-in Model Arena sample below is the fallback if generation takes longer than the allotted time.

| Time | Show | Say |
| --- | --- | --- |
| 0:00–0:25 | Introduce a pump panel and its public question. | An operator inspecting a panel needs to read the right instruments and apply the stated rule. PanelProof tests those skills with fictional equipment and rules. |
| 0:25–0:55 | Generate a fresh panel with a visible seed and show the question and allowed answer format. | The factory creates the image, question, and deterministic reference together. The evaluated model receives the public task. |
| 0:55–1:25 | Submit a human or recorded answer before revealing the reference. Compare a semantic variant with a nuisance variant. | Change the evidence across a rule threshold and the expected answer changes. Change the presentation without changing evidence and the expected answer holds. |
| 1:25–2:05 | Reveal the independently measured pixel evidence and rule verdict for a validated sample. | The verifier recovers readings from the raster and checks the verdict. Show how one reading, its uncertainty, and its instrument label support this answer. |
| 2:05–2:40 | Open the actual frozen report, or a clearly labeled offline demo fixture for rehearsal. | Show one measured success and one failure if available. Point to sample counts and how invalid responses or provider failures affect each accuracy denominator. |
| 2:40–3:00 | Show the release source SHA, manifest, and reproduction instructions. | These artifacts identify the source and benchmark inputs for reruns. State the remaining simulation and model-access limits. |

## Arena sample and inspector

| Step | Public demo ID | What to point out |
| --- | --- | --- |
| Semantic comparison | `p_784449ff7096f562` | PUMP A outlet stays at 600 kPa. Inlet moves from 40 to 500 kPa, so the pressure difference crosses the 300 kPa threshold and the state changes from NORMAL to LOW_PRESSURE. |
| Nuisance comparison | `p_114a1f1fc1ae6b9c` | The text shrinks. PUMP A's needles and lamps stay the same, so its state stays NORMAL. |
| Evidence Inspector | `t_4ca4005a1f640860` | Select the base task and click **Reveal evidence**. Point to the raster readings and diagram regions supporting the answer. |

Open **Run Reports** using the locally generated aggregates. The offline report is labeled **DEMO ONLY**. Keep the artifact used by the view alongside the release notes. The [reproduction commands](../README.md#quickstart) generate the report locally.

## Five slides

1. **Problem** — reading and reasoning from fictional pump panels.
2. **Factory** — seeded images, public questions, and deterministic references.
3. **Validation** — independent raster readings and rules, rejection checks, and paired variants.
4. **Evidence** — judge interaction, real model findings when measured, and an example failure.
5. **Reproduce** — release SHA, manifest, command, and limitations.
