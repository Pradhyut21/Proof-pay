# Blinded human audit

Use two reviewers to judge whether the panel and public rules support a clear answer. The audit is separate from the raster verifier, Rust solver, and model evaluation. A generated pack starts with zero completed reviews.

## Prepare the reviewer pack

Run from the repository root. Supply a local dataset bundle with `public/tasks.jsonl`, `private/tasks.jsonl`, and its `images/` directory. The Python standard library is sufficient.

```sh
python scripts/human_audit.py prepare \
  --dataset data/build/dev \
  --selection path/to/pilot/selection.json \
  --out panelproof-human-review.zip
```

With `--selection`, the tool keeps the order of the existing `task_ids` array and checks that every task is unique, accepted and in the Dev split. To choose a new reproducible review sample, replace `--selection` with `--limit 50 --seed 0`. The selector rotates among skills, ranks tasks by the selection seed and stable task IDs, and reports the actual count when fewer than requested are eligible.

The ZIP contains `review.html`, pixel-only PNGs, instructions, and one blank CSV each for reviewers A and B. It exposes opaque review IDs, public questions and rules, and allowed response options or units. Public response schema examples and defaults, source IDs, source paths, private references, tolerances, seeds, annotations and model answers are excluded. Prepare from the same pinned bundle and same selection for a byte-identical archive.

Extract before opening `review.html`. Share the common page and panels with both reviewers, and each reviewer’s own CSV with that reviewer. Ask them to finish independently and return their CSVs privately before discussing any disagreements. Completed forms may contain private notes and belong outside Git.

## Summarize paired reviews

```sh
python scripts/human_audit.py summarize \
  --reviewer-a reviewer_A_completed.csv \
  --reviewer-b reviewer_B_completed.csv \
  --out human-review-agreement.json
```

The summary verifies the pack ID, reviewer roles and common review IDs. Each row records `VALID`, `AMBIGUOUS`, `INSUFFICIENT`, `UNSURE`, or a blank for an unreviewed item. The primary report gives the count with both verdicts, observed agreement, a contingency table and unweighted Cohen’s κ. κ is null when there are no paired verdicts or the observed marginals make it undefined.

Exact answer agreement uses tasks both reviewers marked `VALID` with two nonblank answers. It compares text after trimming surrounding whitespace, so numerical formatting or unit spelling can differ. The agreement report gives aggregate counts and contains neither submitted answers nor notes. It measures agreement between the submitted judgments. Correctness against a reference key and verified reviewer independence require separate evidence.
