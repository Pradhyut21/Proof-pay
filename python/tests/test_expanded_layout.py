import random
from pathlib import Path

import pytest

from panelproof.mutations import make_nuisance, truth_signature, validate_variant
from panelproof.render import check_layout, png_bytes, render_scene
from panelproof.scene import generate_scene, load_config, scene_from_dict
from panelproof.validate import compare_trace_to_scene
from panelproof.verify import verify_png

EXPANDED_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "generator-expanded.yaml"


def columns_config(theme=None):
    cfg = load_config(EXPANDED_CONFIG)
    cfg.update(pumps={"min": 2, "max": 2}, two_pump_arrangements=["cols"])
    if theme is not None:
        cfg["themes"] = [theme]
    return cfg


def test_expanded_generator_produces_three_layouts_from_fixed_seeds():
    cfg = load_config(EXPANDED_CONFIG)
    scenes = [generate_scene(f"expanded-mix:{index}", cfg) for index in range(40)]
    assert {scene.layout_family() for scene in scenes} == {"1p-single", "2p-rows", "2p-cols"}
    assert all(not check_layout(scene) for scene in scenes)


def test_layout_choice_preserves_legacy_readings_and_rng():
    seed = "legacy-two-pump-columns"
    default = load_config() | {"pumps": {"min": 2, "max": 2}}
    original = generate_scene(seed, default)
    rows = generate_scene(seed, default | {"two_pump_arrangements": ["rows"]})
    cols = generate_scene(seed, default | {"two_pump_arrangements": ["cols"]})

    assert original.layout_family() == "2p-rows"
    assert rows.to_dict() == original.to_dict()
    assert cols.layout_family() == "2p-cols"
    assert truth_signature(cols) == truth_signature(original)
    assert cols.theme == original.theme
    assert cols.font_scale == original.font_scale


def test_column_png_is_deterministic_and_survives_scene_serialization():
    cfg = columns_config()
    scene = generate_scene("deterministic-columns", cfg)
    repeated = generate_scene("deterministic-columns", cfg)
    restored = scene_from_dict(scene.to_dict())
    image = render_scene(scene)
    encoded = png_bytes(image)

    assert scene.pumps[0].module[2] < scene.pumps[1].module[0]
    assert image.size == (1280, 960)
    assert encoded == png_bytes(render_scene(repeated))
    assert encoded == png_bytes(render_scene(restored))
    assert restored.layout_family() == "2p-cols"

    for pump in scene.pumps:
        upper, lower = pump.gauges
        assert upper.cx == lower.cx
        assert upper.cy + upper.r + 44 < lower.cy - lower.r
        assert upper.r >= 120 and lower.r >= 120


@pytest.mark.parametrize("theme", ["daylight", "slate", "sand", "teal"])
def test_column_raster_recovers_both_named_pumps(theme):
    scene = generate_scene(f"column-verify:{theme}:0", columns_config(theme))
    trace = verify_png(png_bytes(render_scene(scene)))

    assert trace["status"] == "verified", trace["pumps"]
    assert {pump["pump_id"] for pump in trace["pumps"]} == {"A", "B"}
    for pump in trace["pumps"]:
        assert set(pump["gauges"]) == {"INLET", "OUTLET"}
        assert set(pump["lamps"]) == {"RUN", "ALARM"}
    assert compare_trace_to_scene(trace, scene)["agree"]


def test_column_nuisance_relayout_preserves_answers_and_raster_recovery():
    config = columns_config("daylight")
    scene = generate_scene("column-verify:daylight:0", config)
    variants = {}
    for seed in range(40):
        variant = make_nuisance(scene, random.Random(seed))
        if variant and variant.edit in {"gauge_order", "lamp_order"}:
            variants.setdefault(variant.edit, variant)
    assert set(variants) == {"gauge_order", "lamp_order"}
    for variant in variants.values():
        assert not validate_variant(scene, variant)
        assert variant.scene.layout_family() == "2p-cols"
        assert not check_layout(variant.scene)
        assert truth_signature(variant.scene) == truth_signature(scene)
        trace = verify_png(png_bytes(render_scene(variant.scene)))
        assert compare_trace_to_scene(trace, variant.scene)["agree"]
