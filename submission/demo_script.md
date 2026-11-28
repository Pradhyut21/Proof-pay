# PanelProof walkthrough

The recorded walkthrough runs **2:55**. The opening uses the Industrial Gauge Video Dataset to explain how to read a moving instrument. The app sections use PanelProof development tasks with generated pump panels and fictional operating rules. [Fu et al., Industrial Gauge Video Dataset for Evaluating MMLM Dynamic Meter Reading, CC BY 4.0](https://doi.org/10.5281/zenodo.20624895)

| Time | Chapter | What it shows |
| --- | --- | --- |
| 0:00 | Real gauges | See a moving dial, a linear index, and Vernier markings. |
| 0:50 | Benchmark design | A reader first recovers a value, then applies the rule. |
| 1:27 | Task Factory | Generate development panels and inspect the question. |
| 1:39 | Model Arena | Submit NORMAL on both sides. Reveal why the expected state changes when the pressure difference crosses the threshold. |
| 2:01 | Evidence Inspector | Reveal the reference and the independent pixel readings behind a scored task. |
| 2:13 | Run Reports | Inspect a fixture report labeled **DEMO ONLY**. |
| 2:23 | Evaluation and reproduction | Explain matched inputs, the clean-render scope, and how to rerun the benchmark. |

## Arena sample and inspector

| Step | Development ID | What to point out |
| --- | --- | --- |
| Generate | Seed `judge-rehearsal` | Choose two panels and inspect the public question. |
| Semantic comparison | `p_784449ff7096f562` | OUTLET stays at 600 kPa and INLET moves from 40 to 500 kPa. The difference drops from 560 to 100 kPa, crossing the 300 kPa threshold. |
| Formatting comparison | `p_114a1f1fc1ae6b9c` | Text size changes. The readings, RUN state, and expected answer stay fixed. |
| Evidence Inspector | `t_4ca4005a1f640860` | Click **Reveal evidence** to see the recovered readings and the reference. |

The 15-slide deck uses the organizer template. It includes the system design, prototype captures, validation charts, and a Links slide with an editable video field. [Submission handoff](DELIVERABLE.md) · [Local quickstart](../README.md#quickstart)
