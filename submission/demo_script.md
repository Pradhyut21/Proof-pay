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

## Organizer deck

Use the organizer's submission template and enter the exact registered team and leader names on the cover. [Deck template](https://docs.google.com/presentation/d/1fXZJ86GvJ-UnR4C7CkeWoTnzNqC7-gznV7efty8Su50/edit)

| Template slide | PanelProof content |
| --- | --- |
| Cover | Registered team and leader names. Track 2, Visual Task Factory. PanelProof measures whether models can read gauges, link evidence to the right pump, and apply operational rules. |
| Idea brief | Generate synthetic pump panels, write grounded questions, and independently verify deterministic reference answers. Evaluate existing vision models under matched input conditions. |
| Opportunity and differentiation | A model can read a plausible value yet attach it to the wrong pump or ignore the rule threshold. Independent pixel readings and controlled visual pairs help locate those failures. |
| Features | Show the seeded Factory, Arena comparison, Evidence Inspector, and report. Use an actual semantic pair and nuisance pair. |
| Process | Seed → render → generate questions and references → verify pixels and rules → freeze grouped tasks → evaluate models → score and report. |
| Wireframes or mock diagrams, optional | Use actual product screenshots if this slide is included. |
| Architecture | Diagram the Python generator, raster verifier and runner, Rust verifier and scorer, Axum/SQLite demo service, and Next.js console. Mark the public task boundary and authorized evidence reveal. |
| Technologies | List Python, Pillow, OpenCV, Rust, Axum, SQLite, Next.js, and Docker. List evaluated provider models and revisions after live runs. |
| Estimated cost, optional | Use actual tracked costs if available, with scope and request counts. |
| Deliverables | Link the pinned source, sample tasks, validation logs, technical docs, measured results when available, and recorded walkthrough. Label offline report images **DEMO ONLY**. |
| Closing | Preserve the template closing slide. |

Record the walkthrough from the running app. Show a fresh generation, one correct and one incorrect scored response, and the independent evidence. Close on the final artifact checksums and the scope of the measured results.
