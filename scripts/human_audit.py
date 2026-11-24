"""Prepare a blinded two-reviewer PanelProof audit and summarize paired judgments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import zipfile
import zlib
from collections import Counter, defaultdict, deque
from pathlib import Path

REVIEW_FIELDS = ("pack_id", "reviewer", "review_id", "verdict", "answer", "notes")
VERDICTS = ("VALID", "AMBIGUOUS", "INSUFFICIENT", "UNSURE")
IMAGE_PATH = re.compile(r"images/[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.png")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PIXEL_CHUNKS = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

INSTRUCTIONS = """PanelProof blinded human review

Open review.html locally in a browser. Each panel, question, public rule, and
answer format is keyed by its Review ID. The page works offline.

1. Send the shared review page and panels to both reviewers. Send reviewer_A.csv
   only to reviewer A and reviewer_B.csv only to reviewer B.
2. Review independently without consulting the other reviewer, model answers,
   generator data, or reference keys. Do not discuss items before returning forms.
3. Keep all rows and identifiers. Fill verdict, answer, and optional notes.
   VALID: the image and public rules support one clear answer.
   AMBIGUOUS: multiple answers or interpretations are defensible.
   INSUFFICIENT: essential visual evidence is missing, unreadable, or unusable.
   UNSURE: you cannot confidently assign any of the other judgments.
   Leave the verdict blank for items you have not reviewed.
4. For VALID items, enter the answer as instructed next to the panel. Use the
   listed category spelling or the integer value in thousandths, one space,
   and the requested unit. For example, a reading of 1.5 bar is entered as
   "1500 bar". Exact answer agreement compares the two trimmed texts.
5. Return your completed CSV privately. Keep the file and its notes out of Git.

This measures reviewer agreement. The pack contains no reference key, and the
report cannot measure correctness against reference answers or verify reviewer
independence.
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_rows(bundle: Path, rel: str) -> dict[str, dict]:
    path = (bundle / rel).resolve(strict=True)
    if not path.is_relative_to(bundle):
        raise ValueError(f"{rel} resolves outside the dataset")
    result = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = row.get("task_id") if isinstance(row, dict) else None
            if not isinstance(key, str) or not key or key in result:
                raise ValueError(
                    f"{rel} row {line_number} has a missing or duplicate task ID"
                )
            result[key] = row
    return result


def selected_ids(
    public: dict, private: dict, limit: int, seed: int, pilot_selection: Path | None
) -> tuple[list[str], int]:
    buckets = defaultdict(list)
    for key, row in private.items():
        if row.get("split") == "dev" and row.get("validation_status") == "accepted":
            if key not in public:
                raise ValueError("An accepted development task has no public record")
            skill = row.get("skill")
            if not isinstance(skill, str) or not skill:
                raise ValueError("An accepted development task is missing its skill")
            buckets[skill].append(key)
    eligible = sum(map(len, buckets.values()))
    if not eligible:
        raise ValueError("No accepted development tasks are available to audit")
    if pilot_selection is not None:
        agreed = json.loads(pilot_selection.read_text(encoding="utf-8"))["task_ids"]
        accepted = {key for group in buckets.values() for key in group}
        if (
            not isinstance(agreed, list)
            or not 1 <= len(agreed) <= 100
            or not all(isinstance(key, str) and key in accepted for key in agreed)
            or len(set(agreed)) != len(agreed)
        ):
            raise ValueError(
                "Pilot selection must contain 1–100 unique accepted development tasks"
            )
        return agreed, eligible

    def rank(value: str, namespace: str) -> tuple[str, str]:
        return digest(f"{seed}:{namespace}:{value}".encode()), value

    strata = deque(
        deque(sorted(buckets[name], key=lambda key: rank(key, "task")))
        for name in sorted(buckets, key=lambda name: rank(name, "skill"))
    )
    selected = []
    while strata and len(selected) < limit:
        group = strata.popleft()
        selected.append(group.popleft())
        if group:
            strata.append(group)
    return selected, eligible


def image_bytes(bundle: Path, rel: str, expected_hash: str) -> bytes:
    if not isinstance(rel, str) or not IMAGE_PATH.fullmatch(rel):
        raise ValueError("Invalid public image path")
    path = (bundle / rel).resolve(strict=True)
    if not path.is_relative_to(bundle / "images") or not path.is_file():
        raise ValueError("A panel image resolves outside the image directory")
    with path.open("rb") as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(PNG_MAGIC):
        raise ValueError("A panel image is not a size-bounded PNG")
    if digest(data) != expected_hash:
        raise ValueError("A panel image does not match its accepted SHA-256")

    offset = len(PNG_MAGIC)
    kinds = []
    while offset + 12 <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + size
        if kind not in PIXEL_CHUNKS or end > len(data):
            raise ValueError(
                "A panel PNG contains non-pixel metadata or a malformed chunk"
            )
        checksum = int.from_bytes(data[end - 4 : end], "big")
        if zlib.crc32(data[offset + 4 : end - 4]) != checksum:
            raise ValueError("A panel PNG chunk does not match its checksum")
        kinds.append(kind)
        offset = end
        if kind == b"IEND":
            break
    if (
        offset != len(data)
        or kinds[:1] != [b"IHDR"]
        or kinds[-1:] != [b"IEND"]
        or b"IDAT" not in kinds
    ):
        raise ValueError("A panel PNG is incomplete or has trailing data")
    return data


def answer_format(schema: dict) -> str:
    # Copy only allowed response options, never examples, defaults, or arbitrary schema metadata.
    props = schema["properties"]
    kind = props["kind"]["enum"]
    if kind == ["category"]:
        choices = props["value"]["enum"]
        if (
            isinstance(choices, list)
            and len(choices) >= 2
            and all(isinstance(x, str) and x for x in choices)
        ):
            return (
                "Enter one category exactly as shown. Choices are "
                + ", ".join(choices)
                + "."
            )
    if kind == ["numeric"]:
        units = props["unit"]["enum"]
        if (
            isinstance(units, list)
            and units
            and all(isinstance(x, str) and x for x in units)
        ):
            return (
                "Enter an integer in thousandths of the unit, then the unit. "
                "A reading of 1.5 bar is entered as 1500 bar. Allowed units are "
                + ", ".join(units)
                + "."
            )
    raise ValueError("Unsupported public answer format")


def review_page(tasks: list[dict]) -> str:
    blocks = []
    for task in tasks:
        rid = task["review_id"]
        blocks.append(
            f'<section><h2>{rid}</h2><img src="panels/{rid}.png" alt="Control panel {rid}">'
            f"<p><strong>Question</strong> {html.escape(task['question'])}</p>"
            f"<p><strong>Public rules</strong> {html.escape(task['public_rules'])}</p>"
            f"<p><strong>Answer format</strong> {html.escape(task['answer_format'])}</p></section>"
        )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>PanelProof review</title>'
        "<style>body{font:1rem system-ui,sans-serif;max-width:64rem;margin:2rem auto;padding:0 1rem}"
        "section{border-top:1px solid #aaa;margin-top:2rem;padding:1rem 0}"
        "img{display:block;max-width:100%;height:auto}p{white-space:pre-wrap}</style>"
        "<h1>PanelProof blinded review</h1><p>Use the Review ID on your own worksheet.</p>"
        + "\n".join(blocks)
        + "</html>\n"
    )


def worksheet(pack: str, reviewer: str, tasks: list[dict]) -> str:
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\r\n")
    writer.writerow(REVIEW_FIELDS)
    for task in tasks:
        writer.writerow([pack, reviewer, task["review_id"], "", "", ""])
    return text.getvalue()


def archive_entry(archive: zipfile.ZipFile, name: str, data: str | bytes) -> None:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def prepare(
    dataset: Path, out: Path, limit: int, seed: int, pilot_selection: Path | None = None
) -> dict:
    if out.suffix.lower() != ".zip" or not 1 <= limit <= 100:
        raise ValueError("Choose a .zip output and a limit between 1 and 100")
    dataset = dataset.resolve(strict=True)
    public = load_rows(dataset, "public/tasks.jsonl")
    private = load_rows(dataset, "private/tasks.jsonl")
    selection, eligible = selected_ids(public, private, limit, seed, pilot_selection)

    tasks = []
    for index, key in enumerate(selection, 1):
        task = public[key]
        question, rules = task["question"], task["public_rules"]
        if (
            not isinstance(question, str)
            or not isinstance(rules, str)
            or not question.strip()
            or not rules.strip()
        ):
            raise ValueError("A public task has a missing question or rule")
        tasks.append(
            {
                "review_id": f"R{index:03d}",
                "question": question,
                "public_rules": rules,
                "answer_format": answer_format(task["response_schema"]),
                "image_sha256": private[key]["image_sha256"],
            }
        )
    pack_id = (
        "pack-"
        + digest(json.dumps(tasks, sort_keys=True, ensure_ascii=False).encode())[:24]
    )

    opened = False
    try:
        with zipfile.ZipFile(out, "x") as archive:
            opened = True
            archive_entry(archive, "INSTRUCTIONS.txt", INSTRUCTIONS)
            archive_entry(archive, "review.html", review_page(tasks))
            for reviewer in ("A", "B"):
                archive_entry(
                    archive,
                    f"reviewer_{reviewer}.csv",
                    worksheet(pack_id, reviewer, tasks),
                )
            for task, key in zip(tasks, selection, strict=True):
                png = image_bytes(
                    dataset, public[key]["image_path"], task["image_sha256"]
                )
                archive_entry(archive, f"panels/{task['review_id']}.png", png)
    except BaseException:
        if opened:
            out.unlink(missing_ok=True)
        raise
    return {
        "pack_id": pack_id,
        "eligible_dev_tasks": eligible,
        "selected_tasks": len(tasks),
        "reviewed_tasks": 0,
    }


def read_review(path: Path, reviewer: str) -> tuple[str, dict[str, tuple[str, str]]]:
    rows = {}
    packs = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != REVIEW_FIELDS:
            raise ValueError(f"Reviewer {reviewer} worksheet has unexpected columns")
        for line, row in enumerate(reader, 2):
            verdict = (row.get("verdict") or "").strip().upper()
            rid = row.get("review_id") or ""
            pack = row.get("pack_id") or ""
            if (
                None in row
                or any(value is None for value in row.values())
                or row.get("reviewer") != reviewer
                or not re.fullmatch(r"R[0-9]{3}", rid)
                or rid in rows
                or not re.fullmatch(r"pack-[a-f0-9]{24}", pack)
                or (verdict and verdict not in VERDICTS)
            ):
                raise ValueError(f"Invalid or duplicate reviewer {reviewer} row {line}")
            packs.add(pack)
            rows[rid] = verdict, (row["answer"] or "").strip()
    if len(packs) != 1:
        raise ValueError(f"Reviewer {reviewer} must use one nonempty pack")
    return packs.pop(), rows


def summarize(reviewer_a: Path, reviewer_b: Path) -> dict:
    pack_a, a = read_review(reviewer_a, "A")
    pack_b, b = read_review(reviewer_b, "B")
    if pack_a != pack_b or a.keys() != b.keys():
        raise ValueError(
            "The two worksheets must preserve the same pack and Review IDs"
        )

    paired = sorted(rid for rid in a if a[rid][0] and b[rid][0])
    first = Counter(a[rid][0] for rid in paired)
    second = Counter(b[rid][0] for rid in paired)
    agreements = sum(a[rid][0] == b[rid][0] for rid in paired)
    n = len(paired)
    chance = sum(first[v] * second[v] for v in VERDICTS)
    denominator = n * n - chance
    both_valid = [rid for rid in paired if a[rid][0] == b[rid][0] == "VALID"]
    with_answers = [rid for rid in both_valid if a[rid][1] and b[rid][1]]
    exact = sum(a[rid][1] == b[rid][1] for rid in with_answers)
    return {
        "pack_id": pack_a,
        "worksheet_tasks": len(a),
        "reviewer_verdicts": {
            "A": dict(Counter(v for v, _ in a.values() if v)),
            "B": dict(Counter(v for v, _ in b.values() if v)),
        },
        "primary_verdict_agreement": {
            "n": n,
            "agreements": agreements,
            "rate": agreements / n if n else None,
            "cohen_kappa": (agreements * n - chance) / denominator
            if denominator
            else None,
            "contingency": {
                va: {
                    vb: sum(a[rid][0] == va and b[rid][0] == vb for rid in paired)
                    for vb in VERDICTS
                }
                for va in VERDICTS
            },
        },
        "exact_answer_agreement": {
            "both_valid": len(both_valid),
            "n": len(with_answers),
            "agreements": exact,
            "rate": exact / len(with_answers) if with_answers else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packing = commands.add_parser("prepare")
    packing.add_argument("--dataset", type=Path, required=True)
    packing.add_argument("--out", type=Path, required=True)
    packing.add_argument(
        "--limit", type=int, help="Maximum number of tasks to select, defaults to 50"
    )
    packing.add_argument(
        "--seed", type=int, help="Selection seed only, separate from generator seeds"
    )
    packing.add_argument(
        "--selection",
        type=Path,
        help="Existing pilot selection.json with a task_ids array",
    )
    reporting = commands.add_parser("summarize")
    reporting.add_argument("--reviewer-a", type=Path, required=True)
    reporting.add_argument("--reviewer-b", type=Path, required=True)
    reporting.add_argument("--out", type=Path)
    options = parser.parse_args()
    try:
        if options.command == "prepare":
            if options.selection is not None and (
                options.limit is not None or options.seed is not None
            ):
                raise ValueError("Use --selection without --limit or --seed")
            limit = 50 if options.limit is None else options.limit
            seed = 0 if options.seed is None else options.seed
            result = prepare(
                options.dataset, options.out, limit, seed, options.selection
            )
        else:
            result = summarize(options.reviewer_a, options.reviewer_b)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if options.command == "summarize" and options.out:
            with options.out.open("x", encoding="utf-8", newline="\n") as output:
                output.write(text)
        print(text, end="")
        return 0
    except (KeyError, TypeError, ValueError, OSError, csv.Error) as error:
        if isinstance(error, (KeyError, TypeError, json.JSONDecodeError)):
            print(
                "human_audit: invalid input record or response schema", file=sys.stderr
            )
        else:
            print(f"human_audit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
