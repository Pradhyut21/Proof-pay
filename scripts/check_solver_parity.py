"""Compare the Python and Rust solvers on seeded synthetic scene records."""

import argparse
import json
import os
import random
import sys
from dataclasses import asdict
from pathlib import Path

from panelproof.rules import PUMP_RULE
from panelproof.rust_bridge import RustVerificationError, verify_scenes
from panelproof.schemas import Scene

PRESSURE_UNITS = ("kPa", "bar", "psi")
PRESSURE_LIMITS = {"kPa": 900_000, "bar": 9_000, "psi": 130_000}


def sample_scenes(count: int, seed: int) -> list[Scene]:
    rng = random.Random(seed)
    scenes = []
    for index in range(count):
        equipment = []
        for pump_id in range(1, 2 + index % 2):
            if (index + pump_id) % 5 == 0:
                inlet_unit = outlet_unit = "kPa"
                inlet = rng.randint(0, 500_000)
                outlet = inlet + 299_999 + (index + pump_id) // 5 % 3
            else:
                inlet_unit, outlet_unit = rng.choices(PRESSURE_UNITS, k=2)
                inlet = rng.randint(-2_000, PRESSURE_LIMITS[inlet_unit])
                outlet = rng.randint(-2_000, PRESSURE_LIMITS[outlet_unit])
            equipment.append(
                {
                    "id": f"pump-{pump_id}",
                    "label": f"Pump {pump_id}",
                    "inlet": {"unit": inlet_unit, "value_milli": inlet},
                    "outlet": {"unit": outlet_unit, "value_milli": outlet},
                    "run": bool(rng.randrange(2)),
                    "alarm": bool(rng.randrange(2)),
                }
            )
        scenes.append(
            Scene.model_validate(
                {
                    "schema_version": "1.0.0",
                    "base_scene_id": f"parity-{index:05d}",
                    "seed": rng.randrange(2**32),
                    "layout_family": "solver-fixture",
                    "style_family": "solver-fixture",
                    "equipment": equipment,
                }
            )
        )
    return scenes


def main() -> int:
    executable = "pp.exe" if os.name == "nt" else "pp"
    local_binary = Path(__file__).resolve().parents[1] / "target" / "debug" / executable
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pp", default=local_binary if local_binary.is_file() else "pp"
    )
    parser.add_argument("--count", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=4628501)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")

    scenes = sample_scenes(args.count, args.seed)
    try:
        verified = verify_scenes(
            (scene.model_dump(mode="json") for scene in scenes),
            executable=args.pp,
            required=True,
        )
    except RustVerificationError as exc:
        parser.error(str(exc))
    if verified is None:
        parser.error("Rust verifier is required")

    mismatches = []
    for scene, actual in zip(scenes, verified, strict=True):
        expected = {
            "base_scene_id": scene.base_scene_id,
            "equipment": [
                {"id": pump.id, **asdict(PUMP_RULE.solve(pump))}
                for pump in scene.equipment
            ],
        }
        if expected != actual:
            mismatches.append(
                {"scene": scene.base_scene_id, "expected": expected, "actual": actual}
            )
    for mismatch in mismatches[:5]:
        print(json.dumps(mismatch), file=sys.stderr)
    print(
        json.dumps(
            {
                "seed": args.seed,
                "scenes_checked": len(scenes),
                "pumps_checked": sum(len(scene.equipment) for scene in scenes),
                "mismatches": len(mismatches),
            }
        )
    )
    return int(bool(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
