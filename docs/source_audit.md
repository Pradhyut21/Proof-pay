# Source audit (PP-02)

Audit date: 2026-11-24. Machine-readable record: [`reference/upstream_manifest.json`](../reference/upstream_manifest.json).
Dataset-specific terms: [`docs/dataset_sources.md`](dataset_sources.md). Notices for what this repository ships:
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## Method and what was actually run

Every command below is tagged **run** (executed during this audit) or **documented** (copied from upstream
documentation and *not* executed). No upstream script, notebook, weight file or dataset was downloaded or executed, so
no upstream artifact was reproduced. Third-party scripts were not run, so there was nothing to audit before execution
beyond reading entry points and dependency manifests.

| Tag | Command | Result |
| --- | --- | --- |
| run | `gh api repos/<owner>/<repo>` (license, default branch, archived) | one call per repository, results in the matrix |
| run | `gh api repos/<owner>/<repo>/commits/<sha>` | all six issue-supplied SHAs exist; commit dates in the matrix |
| run | `gh api repos/<owner>/<repo>/git/trees/<sha>` | top-level layout recorded |
| run | `gh api .../contents/<file>?ref=<sha>` for MeasureBench `data_machine/requirements.txt` and `README.md`, ETH `pyproject.toml`, CLEVR `LICENSE` | contents read, not executed |
| run | `curl https://huggingface.co/api/datasets/FlagEval/MeasureBench` | revision `93c00167…`, `cc-by-sa-4.0`, not gated |
| run | `curl https://devpost.com/software/<slug>` for four slugs | HTTP 200 each; page contents **not** read |
| documented | MeasureBench: `python data_machine/generate_data.py -l`, `python evaluation/evaluate.py` | not run. Needs `bpy==3.6.0` (Blender) |
| documented | ETH: `poetry install`, `python pipeline.py ...` with model-weight paths | not run. Needs torch 2.0.0, mmcv 2.0.0, mmdet, mmocr, ultralytics |
| documented | DynaMath: container build from `Dockerfile`, then `dataset_generator/` | not run |
| documented | VLMEvalKit: `python run.py ...` | not run |

## Source matrix

| Reference | Pinned revision | Code license | Entry points | Decision |
| --- | --- | --- | --- | --- |
| MeasureBench code | `d5bb8652dbde6b1b5507f89d37f73993af28b830` (2026-03-26) | **none declared** | `data_machine/`, `evaluation/evaluate.py` | Design reference only. No license means no right to copy code |
| MeasureBench dataset | HF `93c001671055f739bc396c73aa6b2d5e6171abed` | CC BY-SA 4.0 (dataset card) | n/a | Optional external slice, not downloaded (see dataset_sources.md) |
| ETH analog gauge reader | `518cdfaab1e9c7cdabb1ef957e45311fe3f6a47a` (2024-05-13) | MIT | `pipeline.py`, `angle_reading_fit/` | Geometry/calibration reference; ML stack not reused; weight terms unverified |
| Classical Hough reader | `b1759194ee49a0e558f7ff5d77e632ff2ca30d2b` (HEAD on 2026-11-24; the issue gave no SHA) | MIT | `analog_gauge_reader.py` | Reference for the classical approach |
| CLEVR generator | `f0ce2c81750bfae09b5bf94d009f42e055f2cb3a` (archived) | BSD License text + separate `PATENTS` file | `image_generation/`, `question_generation/` | Scene/render/question separation as design. No code reused |
| DynaMath | `598c3c3d732422d29580e9ecf8f2a7928a068fdd` (2024-11-25) | **none declared** | `dataset_generator/`, `evaluation/` | Worst-case seed-group accuracy adopted as a method, reimplemented |
| VLMEvalKit | `2f11dc888838404991214cce0358fff815be7ff6` (2026-11-24) | Apache-2.0 | `run.py`, `vlmeval/dataset/` | Adapter boundary as design reference |
| Henomaly | `d608debec86bb13b69eb7d0d907b6c3aaa9831e2` (2026-10-18) | **AGPL-3.0** | `app/console/`, `docs/research/evidence/` | Review reference only. Must not copy code (AGPL) |
| Devpost: Omnisynth, Henomaly, JengaBench, Agent Gauntlet | none | not assessed | none | **Unverified**: pages returned HTTP 200 but were not read |
| "Legal LLM Safety Metrics" | none | not assessed | none | **Unverified**: not locatable from the material available |

The MeasureBench paper ([arXiv 2510.26865](https://arxiv.org/abs/2510.26865)) was not opened in this audit; claims
attributed to it in the issue text (pointer-localization errors) are **unverified** here.

## Build vs reuse

- **Reuse nothing from the audited repositories.** Two have no license, one is AGPL-3.0, one is archived with a
  patent file, and the rest would pull heavy stacks (Blender, torch/mmcv) onto an 8 GB laptop target. PanelProof has
  its own 2D renderer (`python/src/panelproof/render.py`) and its own classical OpenCV/NumPy verifier
  (`python/src/panelproof/verify.py`).
- **Methods carried over as ideas** (independently implemented, with no code copied): generation separated from scoring
  (MeasureBench, CLEVR); classical needle localization with calibration and an uncertainty estimate (ETH, Hough
  reader); worst-case accuracy over a group of related renderings (DynaMath, used here as "worst group" in
  `metrics.py`); a narrow adapter interface (VLMEvalKit).
- **External sample.** The optional MeasureBench slice stays unbuilt until attribution, share-alike handling, a
  deterministic selection and checksums are decided; see `dataset_sources.md`.

## Novelty statement

PanelProof's claim is narrow: **multi-instrument association** (which gauge and lamp belong to which named pump)
combined with **explicit public rule reasoning**, where every reference answer is **pixel-verified** by a verifier
that sees only the PNG, and where **controlled counterfactual pairs** (semantic flip, meaning-preserving unit change,
nuisance change, removed evidence) test whether the answer follows the evidence. This audit found no evidence for
broader claims (for example that this beats other benchmarks, or that results transfer to real panels). Transfer to
real instruments is untested; the optional real slice is not built. No hackathon award claims are made, and none of
the Devpost material was verified.

## Remaining gaps

1. Paper claims and the four Devpost projects are unverified (pages not read).
2. MeasureBench dataset terms were read from the HF card metadata only; the full card text and the per-sample
   attributions were not reviewed.
3. ETH model-weight licenses were not checked.
4. No upstream command was executed, so none of the "documented" commands is known to work today.
