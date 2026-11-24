import json

import pytest

from panelproof.factory import run_factory


def test_factory_exports_only_answer_flipping_semantic_pairs(tmp_path):
    output = tmp_path / "factory"
    run_factory("verify-semantic-answers", 4, output)
    private = {
        record["task_id"]: record
        for line in (output / "private" / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if (record := json.loads(line))
    }
    pairs = [
        json.loads(line)
        for line in (output / "public" / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    semantic = 0
    for pair in pairs:
        before, after = (private[task_id] for task_id in pair["task_ids"])
        if after["variant_kind"] == "semantic":
            semantic += 1
            assert before["skill"] == after["skill"]
            assert before["answer"] != after["answer"]
        else:
            assert before["answer"] == after["answer"]
    assert semantic == 4


def test_factory_preserves_a_nonempty_output_directory(tmp_path):
    unrelated = tmp_path / "existing.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty directory"):
        run_factory("output-guard", 1, tmp_path)
    assert unrelated.read_text(encoding="utf-8") == "keep"
