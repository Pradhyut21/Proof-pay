# Candidate validation

The candidate validator checks a task before dataset export. Call `panelproof.validation.validate_candidate` with its public and private records, the PNG bytes, and the evidence from independent checks. It performs no filesystem access or model calls.

- Pass the bytes read from the public task's image path plus the bytes from a separate render of the same scene. The image path must be a relative `images/<id>.png` path. The task IDs and the private SHA-256 must match.
- Pass the expected dimensions when the run has a fixed output size. PNGs must fit the byte and dimension limits, have valid chunks and raster data, and contain only pixel-related chunks. Evidence boxes must fit inside the decoded image.
- Supply `AnswerabilityEvidence` from the question builder. If the question depends on a threshold or relative reading, supply the observed and required margins. Set `margin_required=False` for a question whose answer has no applicable margin.
- Pass `RasterEvidence` after the independent verifier has recovered the answer and regions from the PNG and the public conventions. Attach the task ID, image SHA-256 and verifier version to that record. Supply the separately derived Rust answer as `secondary_answer`. The validator compares both outputs to the private reference.
- Keep `CandidateReport.to_dict()` and `summarize_reports()` with internal validation artifacts. The summary counts accepted, rejected and pending candidates by skill, and check outcomes and reason codes.

A failed check rejects the candidate. A missing required input leaves the candidate pending unless a separate check has already failed. Acceptance here requires all candidate checks to pass. The dev pilot still needs generated scenes, the integrated raster verifier, and measured layout, legibility and shortcut checks. Dataset export also needs group and counterfactual audits.

The unit tests use generated image fixtures and simulated verifier results to exercise the interface. They provide no measurement of the generator or raster verifier.
