import ast
from pathlib import Path

import cv2
import numpy as np
import pytest
from manual_panel import panel, png

from panelproof.render import png_bytes, render_scene
from panelproof.scene import generate_scene, scene_from_dict
from panelproof.validate import compare_trace_to_scene
from panelproof.verify import verify_png

SRC = Path(__file__).resolve().parents[1] / "src" / "panelproof" / "verify.py"


def v(**kw):
    t = verify_png(png(panel(**kw)))
    return t, t["pumps"][0]


def test_verifier_imports_nothing_from_generator():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 1}
    assert not (mods & {"scene", "render", "mutations", "validate", "question_bridge", "cli", "export"}), mods


def test_manual_fixture_reads_exact_ticks():
    _, p = v()  # inlet tick 10 => 200 kPa, outlet tick 27 => 540 kPa
    assert p["verdict"] == "verified"
    assert p["gauges"]["INLET"]["reading_milli"] == 200_000
    assert p["gauges"]["OUTLET"]["reading_milli"] == 540_000
    assert p["derived"]["state"] == "NORMAL" and p["run"] and not p["alarm"]


def test_wrong_lamp_is_seen():
    _, p = v(run=False, alarm=True)
    assert p["run"] is False and p["alarm"] is True and p["derived"]["state"] == "STOPPED"


def test_shifted_needle_half_tick_is_rejected():
    _, p = v(shift_out=-4.5)  # half a minor tick (9 deg)
    assert p["verdict"] == "rejected" and any("needle_between_ticks" in r for r in p["reasons"])


def test_shifted_needle_one_tick_changes_reading():
    _, p = v(shift_out=9.0)  # one tick counter-clockwise => lower reading
    assert p["gauges"]["OUTLET"]["reading_milli"] == 520_000


def test_swapped_captions_follow_visible_labels():
    _, p = v(captions=("OUTLET", "INLET"))
    assert p["gauges"]["INLET"]["reading_milli"] == 540_000 and p["gauges"]["OUTLET"]["reading_milli"] == 200_000
    assert p["derived"]["delta_mkpa"] == -340_000 and p["derived"]["state"] == "LOW_PRESSURE"


def test_unit_label_is_honoured_not_assumed():
    _, p = v(inlet_unit="bar", outlet_unit="bar", scale=(0, 6, 1, 5), inlet_tick=10, outlet_tick=27)
    assert p["gauges"]["INLET"]["unit"] == "bar" and p["gauges"]["INLET"]["reading_mkpa"] == 200_000


def test_hidden_label_rejected():
    _, p = v(captions=("INLET", "XX"))
    assert p["verdict"] == "rejected"


def test_unreadable_pump_label_rejected():
    _, p = v(title="PUMP Z")
    assert p["verdict"] == "rejected" and "pump_label_unreadable" in p["reasons"]


def test_flipped_orientation_rejected():
    img = cv2.flip(cv2.imdecode(np.frombuffer(png(panel()), np.uint8), cv2.IMREAD_COLOR), 1)
    t = verify_png(cv2.imencode(".png", img)[1].tobytes())
    assert t["status"] == "rejected"


def test_borderline_exact_threshold_not_guessed():
    # delta exactly 300 kPa (tick 10 -> 200, tick 25 -> 500): uncertainty spans the class boundary
    _, p = v(inlet_tick=10, outlet_tick=25)
    assert p["verdict"] == "rejected" and "uncertainty_spans_class_boundary" in p["reasons"]


def test_just_clear_of_threshold_is_decided():
    _, p = v(inlet_tick=10, outlet_tick=26)  # delta 320, composed uncertainty 20 kPa -> NORMAL
    assert p["derived"]["state"] == "NORMAL"


def test_altered_reference_with_unchanged_image_is_caught():
    scene = generate_scene("pilot:00003")
    trace = verify_png(png_bytes(render_scene(scene)))
    assert compare_trace_to_scene(trace, scene)["agree"]
    d = scene.to_dict()
    g = d["pumps"][0]["gauges"][0]
    g["value_milli"] += 3 * g["major_step_milli"] // g["minor_per_major"]
    assert not compare_trace_to_scene(trace, scene_from_dict(d))["agree"]


def test_altered_raster_with_unchanged_reference_is_caught():
    scene = generate_scene("pilot:00003")
    d = scene.to_dict()
    g = d["pumps"][0]["gauges"][0]
    g["value_milli"] += 3 * g["major_step_milli"] // g["minor_per_major"]
    trace = verify_png(png_bytes(render_scene(scene_from_dict(d))))
    assert not compare_trace_to_scene(trace, scene)["agree"]


def test_deliberate_needle_corruption_is_caught_when_it_flips_the_verdict():
    scene = next(
        s for s in (generate_scene(f"corrupt:{i}") for i in range(200)) if len(s.pumps) == 1 and s.pumps[0].run
    )
    p = scene.pumps[0]
    g = p.gauge("OUTLET")
    good = verify_png(png_bytes(render_scene(scene)))
    if good["status"] != "verified":
        pytest.skip("seed not verifiable")
    sd = scene.to_dict()
    gd = next(x for x in sd["pumps"][0]["gauges"] if x["role"] == "OUTLET")
    new = gd["value_milli"] + (-4 if p.state() == "NORMAL" else 4) * g.minor_milli
    gd["value_milli"] = min(max(new, gd["min_milli"] + g.minor_milli), gd["max_milli"] - g.minor_milli)
    corrupted = scene_from_dict(sd)
    bad = verify_png(png_bytes(render_scene(corrupted)))
    assert not compare_trace_to_scene(bad, scene)["agree"]


def test_glare_over_gauge_never_yields_wrong_verified_pump():
    scene = generate_scene("pilot:00006")
    img = cv2.imdecode(np.frombuffer(png_bytes(render_scene(scene)), np.uint8), cv2.IMREAD_COLOR)
    g = scene.pumps[0].gauges[0]
    ov = img.copy()
    cv2.ellipse(ov, (g.cx, g.cy), (g.r, g.r // 3), 30, 0, 360, (255, 255, 255), -1)
    out = cv2.addWeighted(ov, 0.35, img, 0.65, 0)
    t = verify_png(cv2.imencode(".png", out)[1].tobytes())
    cmp_ = compare_trace_to_scene(t, scene)
    assert all(not pc.get("errors") for pc in cmp_["pumps"])  # rejected or correct, never silently wrong


def test_generated_sample_agrees_with_truth():
    ok = 0
    for i in range(8):
        s = generate_scene(f"agree:{i}")
        t = verify_png(png_bytes(render_scene(s)))
        c = compare_trace_to_scene(t, s)
        assert all(not p.get("errors") for p in c["pumps"])  # never verified-and-wrong
        ok += c["agree"]
    assert ok >= 6
