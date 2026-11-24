import hashlib
import json
import random
import struct
import time

from panelproof.cli import generate_dataset
from panelproof.mutations import (
    make_missing,
    make_nuisance,
    make_preserving,
    make_semantic_flip,
    validate_variant,
)
from panelproof.render import check_layout, png_bytes, render_scene
from panelproof.rule_bridge import THRESHOLD_MKPA
from panelproof.scene import generate_scene
from panelproof.units import convert_milli, from_milli_kpa, round_half_away, to_milli_kpa

ALLOWED_CHUNKS = {b"IHDR", b"IDAT", b"IEND"}


def chunks(data: bytes) -> list[bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    out, i = [], 8
    while i < len(data):
        (n,) = struct.unpack(">I", data[i : i + 4])
        out.append(data[i + 4 : i + 8])
        i += 12 + n
    return out


def test_png_is_byte_identical_for_fixed_seed():
    a = png_bytes(render_scene(generate_scene("det:1")))
    b = png_bytes(render_scene(generate_scene("det:1")))
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
    assert a != png_bytes(render_scene(generate_scene("det:2")))


def test_png_metadata_is_stripped():
    data = png_bytes(render_scene(generate_scene("meta:1")))
    assert set(chunks(data)) <= ALLOWED_CHUNKS, set(chunks(data))
    assert struct.unpack(">II", data[16:24]) == (1280, 960)


def test_200_seeded_layouts_have_no_overlap_or_bounds_violations():
    bad = []
    for i in range(200):
        s = generate_scene(f"layout:{i}")
        errs = check_layout(s)
        if errs:
            bad.append((i, errs))
    assert not bad, bad[:3]


def test_scenes_are_margin_safe_and_ticks_quantized():
    for i in range(100):
        s = generate_scene(f"margin:{i}")
        for p in s.pumps:
            gi, go = p.gauge("INLET"), p.gauge("OUTLET")
            assert abs(p.delta_mkpa() - THRESHOLD_MKPA) >= gi.minor_mkpa + go.minor_mkpa
            for g in (gi, go):
                assert (g.value_milli - g.min_milli) % g.minor_milli == 0
                assert 1 <= g.tick_index() <= g.n_minor - 1


def test_cue_decorrelation_alarm_vs_expected_state():
    agree = total = 0
    for i in range(300):
        for p in generate_scene(f"cue:{i}").pumps:
            total += 1
            agree += p.alarm_consistent()
    assert 0.40 <= agree / total <= 0.60


def test_generate_dataset_manifest_is_reproducible(tmp_path):
    m1 = generate_dataset("repro", 4, tmp_path / "a", None, 1)
    m2 = generate_dataset("repro", 4, tmp_path / "b", None, 2)
    assert m1["manifest_sha256"] == m2["manifest_sha256"]
    assert m1["files"] == m2["files"]
    assert json.loads((tmp_path / "a" / "manifest.json").read_text())["count"] == 4


def test_render_timing_recorded():
    t0 = time.perf_counter()
    for i in range(5):
        png_bytes(render_scene(generate_scene(f"time:{i}")))
    assert (time.perf_counter() - t0) / 5 < 2.0


def test_units_round_half_away_and_conversions():
    from fractions import Fraction

    assert round_half_away(Fraction(5, 2)) == 3 and round_half_away(Fraction(-5, 2)) == -3
    assert to_milli_kpa(1000, "bar") == 100_000 and to_milli_kpa(1000, "kPa") == 1000
    assert to_milli_kpa(1000, "psi") == 6895
    assert from_milli_kpa(100_000, "bar") == 1000
    assert convert_milli(100_000, "kPa", "bar") == 1000


def test_variants_are_valid_and_leave_siblings_intact():
    counts = {"semantic": 0, "preserving": 0, "nuisance": 0, "missing": 0}
    for i in range(40):
        base = generate_scene(f"vv:{i}")
        rng = random.Random(f"vv:{i}")
        for fn in (make_semantic_flip, make_preserving, make_nuisance, make_missing):
            v = fn(base, rng)
            if v:
                assert validate_variant(base, v) == []
                assert v.diff, "variant must record a field-level diff"
                counts[v.kind] += 1
    assert all(c >= 5 for c in counts.values()), counts
