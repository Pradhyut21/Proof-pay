"""Compare independent raster-verifier traces with generator truth (outside the verifier)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .scene import Scene, scene_from_dict
from .verify import VERIFIER_VERSION, verify_png


def compare_trace_to_scene(trace: dict[str, Any], scene: Scene) -> dict[str, Any]:
    """Agreement record. `agree` is True only when every pump is verified and equals truth."""
    out: dict[str, Any] = {"agree": True, "mismatches": [], "pumps": []}
    by_id = {p["pump_id"]: p for p in trace["pumps"] if p.get("pump_id")}
    if len(trace["pumps"]) != len(scene.pumps):
        out["agree"] = False
        out["mismatches"].append(f"module_count {len(trace['pumps'])} != {len(scene.pumps)}")
    for sp in scene.pumps:
        tp = by_id.get(sp.pump_id)
        rec: dict[str, Any] = {"pump": sp.pump_id, "verdict": tp["verdict"] if tp else "missing"}
        if tp is None or tp["verdict"] != "verified":
            rec["reasons"] = tp["reasons"] if tp else ["pump_not_found"]
            out["pumps"].append(rec)
            out["agree"] = False
            continue
        errs = []
        if tp["run"] != sp.run:
            errs.append("run")
        if tp["alarm"] != sp.alarm:
            errs.append("alarm")
        for role in ("INLET", "OUTLET"):
            sg, tg = sp.gauge(role), tp["gauges"][role]
            ticks_off = (tg["reading_milli"] - sg.value_milli) / sg.minor_milli
            rec[f"{role.lower()}_error_ticks"] = round(ticks_off, 3)
            if tg["unit"] != sg.unit:
                errs.append(f"{role}:unit")
            if abs(ticks_off) > 1.0:
                errs.append(f"{role}:reading")
        if tp["derived"]["state"] != sp.state():
            errs.append("state")
        if tp["derived"]["alarm_consistent"] != sp.alarm_consistent():
            errs.append("alarm_consistent")
        rec["errors"] = errs
        if errs:
            out["agree"] = False
            out["mismatches"].append(f"{sp.pump_id}: {','.join(errs)}")
        out["pumps"].append(rec)
    return out


def verify_dataset_dir(root: Path, out: Path | None = None) -> dict[str, Any]:
    """Verify every PNG in a `panelproof generate` directory and compare to private truth."""
    records = [json.loads(line) for line in (root / "private" / "scenes.jsonl").read_text(encoding="utf-8").splitlines()]
    traces, reasons = [], Counter()
    agree = verified = exact = 0
    for rec in records:
        png = (root / "images" / f"{rec['scene_id']}.png").read_bytes()
        trace = verify_png(png)
        scene = scene_from_dict(rec["scene"])
        cmp_ = compare_trace_to_scene(trace, scene)
        traces.append({"scene_id": rec["scene_id"], "trace": trace, "comparison": cmp_})
        verified += trace["status"] == "verified"
        agree += cmp_["agree"]
        for p in trace["pumps"]:
            reasons.update(p["reasons"])
        exact += cmp_["agree"] and all(
            abs(p.get("inlet_error_ticks", 9)) < 1e-9 and abs(p.get("outlet_error_ticks", 9)) < 1e-9
            for p in cmp_["pumps"])
    summary = {
        "verifier_version": VERIFIER_VERSION,
        "scenes": len(records),
        "verified": verified,
        "agree_with_truth": agree,
        "exact_tick_agreement": exact,
        "rejection_reasons": dict(reasons),
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(json.dumps(t, sort_keys=True) for t in traces) + "\n", encoding="utf-8")
        summary["trace_file"] = str(out)
    return summary
