import random

from panelproof.mutations import make_inlet_floor_flip
from panelproof.question_bridge import answer_from_trace, build_questions
from panelproof.render import png_bytes, render_scene
from panelproof.scene import generate_scene
from panelproof.verify import verify_png


def test_inlet_only_counterfactual_flips_the_new_answer_and_keeps_the_delta_answer():
    base = generate_scene("inlet-counterfactual:3")
    variant = make_inlet_floor_flip(base, random.Random(0))
    assert variant is not None
    assert len(variant.diff) == 1 and variant.diff[0]["path"].endswith(".value_milli")
    assert base.pump(variant.pump_id).state() == variant.scene.pump(variant.pump_id).state()

    answers = []
    for scene in (base, variant.scene):
        question = next(
            q for q in build_questions(scene, include_inlet_floor=True)
            if q.pump_id == variant.pump_id and q.kind == "inlet_state"
        )
        trace = verify_png(png_bytes(render_scene(scene)))
        assert trace["status"] == "verified"
        pump = next(p for p in trace["pumps"] if p["pump_id"] == variant.pump_id)
        recovered = answer_from_trace(question, pump)
        assert recovered == question.answer
        answers.append(recovered["value"])
    assert answers == ["NORMAL", "LOW_PRESSURE"]
