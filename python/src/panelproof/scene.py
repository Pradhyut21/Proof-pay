"""Seeded scene model and generation. Pure for a fixed (seed, config).

A *scene* is private truth: values, layout geometry, theme. The public artifact is the PNG.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from . import SCHEMA_VERSION
from .interim_rules import THRESHOLD_MKPA, expected_alarm, pump_state
from .units import repo_root, to_milli_kpa

CANVAS_W, CANVAS_H = 1280, 960
MARGIN, GUTTER = 56, 32
LAMP_COL_W = 190
GAUGE_ROLES = ("INLET", "OUTLET")
LAMP_NAMES = ("RUN", "ALARM")


@dataclass
class Gauge:
    role: str
    unit: str
    min_milli: int
    max_milli: int
    major_step_milli: int
    minor_per_major: int
    value_milli: int
    cx: int = 0
    cy: int = 0
    r: int = 0

    @property
    def n_minor(self) -> int:
        return (self.max_milli - self.min_milli) // self.major_step_milli * self.minor_per_major

    @property
    def minor_milli(self) -> int:
        return self.major_step_milli // self.minor_per_major

    @property
    def value_mkpa(self) -> int:
        return to_milli_kpa(self.value_milli, self.unit)

    @property
    def minor_mkpa(self) -> int:
        return to_milli_kpa(self.minor_milli, self.unit)

    def tick_index(self) -> int:
        return (self.value_milli - self.min_milli) // self.minor_milli


@dataclass
class Pump:
    pump_id: str
    run: bool
    alarm: bool
    gauges: list[Gauge]  # left-to-right order on the panel
    lamp_order: list[str]  # top-to-bottom order, e.g. ["RUN", "ALARM"]
    module: tuple[int, int, int, int] = (0, 0, 0, 0)
    lamps: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # name -> (x, y, r)
    covered: list[str] = field(default_factory=list)  # gauge roles hidden by a cover plate

    def gauge(self, role: str) -> Gauge:
        return next(g for g in self.gauges if g.role == role)

    @property
    def label(self) -> str:
        return f"PUMP {self.pump_id}"

    def state(self) -> str:
        return pump_state(self.run, self.gauge("INLET").value_mkpa, self.gauge("OUTLET").value_mkpa)

    def delta_mkpa(self) -> int:
        return self.gauge("OUTLET").value_mkpa - self.gauge("INLET").value_mkpa

    def alarm_consistent(self) -> bool:
        return self.alarm == expected_alarm(self.state())


@dataclass
class Scene:
    seed: str
    theme: str
    pumps: list[Pump]
    arrangement: str = "single"  # single | cols | rows
    font_scale: float = 1.0
    glare: tuple[int, int, int, int] | None = None  # (cx, cy, rx, ry)
    schema_version: str = SCHEMA_VERSION

    def pump(self, pump_id: str) -> Pump:
        return next(p for p in self.pumps if p.pump_id == pump_id)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self)))

    @property
    def scene_id(self) -> str:
        return "sc_" + hashlib.sha256(canonical_json(self.to_dict())).hexdigest()[:16]

    def layout_family(self) -> str:
        return f"{len(self.pumps)}p-{self.arrangement}"


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def scene_from_dict(d: dict[str, Any]) -> Scene:
    pumps = []
    for p in d["pumps"]:
        gauges = [Gauge(**g) for g in p["gauges"]]
        pumps.append(
            Pump(
                pump_id=p["pump_id"],
                run=p["run"],
                alarm=p["alarm"],
                gauges=gauges,
                lamp_order=list(p["lamp_order"]),
                module=tuple(p["module"]),
                lamps={k: tuple(v) for k, v in p["lamps"].items()},
                covered=list(p.get("covered", [])),
            )
        )
    glare = tuple(d["glare"]) if d.get("glare") else None
    return Scene(
        seed=d["seed"],
        theme=d["theme"],
        pumps=pumps,
        arrangement=d["arrangement"],
        font_scale=d["font_scale"],
        glare=glare,
        schema_version=d["schema_version"],
    )


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else repo_root() / "configs" / "generator.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def config_hash(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(cfg)).hexdigest()


# ---------------------------------------------------------------- layout


def module_rects(n: int, arrangement: str) -> list[tuple[int, int, int, int]]:
    m, g = MARGIN, GUTTER
    if n == 1:
        return [(m + 80, m + 60, CANVAS_W - m - 80, CANVAS_H - m - 60)]
    if arrangement == "cols":
        w = (CANVAS_W - 2 * m - g * (n - 1)) // n
        return [(m + i * (w + g), m + 60, m + i * (w + g) + w, CANVAS_H - m - 60) for i in range(n)]
    h = (CANVAS_H - 2 * m - g * (n - 1)) // n
    return [(m, m + i * (h + g), CANVAS_W - m, m + i * (h + g) + h) for i in range(n)]


def layout_pump(pump: Pump, rect: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = rect
    pump.module = rect
    area_x0, area_x1 = x0 + 16, x1 - LAMP_COL_W
    area_y0, area_y1 = y0 + 64, y1 - 16
    cell_w = (area_x1 - area_x0) // 2
    r = min(150, cell_w // 2 - 12, (area_y1 - area_y0 - 40) // 2)
    cy = area_y0 + (area_y1 - area_y0 - 40) // 2
    for i, g in enumerate(pump.gauges):
        g.cx = area_x0 + cell_w * i + cell_w // 2
        g.cy = cy
        g.r = r
    lx = x1 - LAMP_COL_W // 2 - 4
    yc = (y0 + 64 + y1) // 2
    pump.lamps = {
        name: (lx, yc + (-1 if i == 0 else 1) * 62, 24) for i, name in enumerate(pump.lamp_order)
    }


# ---------------------------------------------------------------- generation


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    keys = sorted(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def _make_gauge(rng: random.Random, cfg: dict[str, Any], role: str, unit: str) -> Gauge:
    lo, hi, step, mpm = rng.choice(cfg["scales"][unit])
    return Gauge(role, unit, lo * 1000, hi * 1000, step * 1000, mpm, 0)


def _sample_pump(rng: random.Random, cfg: dict[str, Any], pump_id: str) -> Pump:
    run = rng.random() < cfg["run_probability"]
    target_normal = rng.random() < 0.5
    ticks = cfg["reading_uncertainty_ticks"]
    for _ in range(2000):
        unit_in = _weighted(rng, cfg["unit_weights"])
        unit_out = _weighted(rng, cfg["unit_weights"])
        gin = _make_gauge(rng, cfg, "INLET", unit_in)
        gout = _make_gauge(rng, cfg, "OUTLET", unit_out)
        gin.value_milli = gin.min_milli + gin.minor_milli * rng.randint(1, gin.n_minor - 1)
        gout.value_milli = gout.min_milli + gout.minor_milli * rng.randint(1, gout.n_minor - 1)
        delta = gout.value_mkpa - gin.value_mkpa
        margin = ticks * (gin.minor_mkpa + gout.minor_mkpa)
        if delta < 0 or abs(delta - THRESHOLD_MKPA) < margin:
            continue
        if (delta >= THRESHOLD_MKPA) != target_normal:
            continue
        break
    else:  # pragma: no cover - guarded by tests
        raise RuntimeError("could not sample a margin-safe pump")
    alarm = rng.random() < cfg["alarm_probability"]
    gauges = [gin, gout]
    if rng.random() < 0.5:
        gauges.reverse()
    lamp_order = list(LAMP_NAMES)
    if rng.random() < 0.5:
        lamp_order.reverse()
    return Pump(pump_id, run, alarm, gauges, lamp_order)


def place_glare(rng: random.Random, scene: Scene) -> tuple[int, int, int, int] | None:
    """A small glare ellipse in the top or bottom margin, away from all evidence."""
    rx, ry = rng.randint(30, 60), rng.randint(10, 16)
    cy = MARGIN // 2 if rng.random() < 0.5 else CANVAS_H - MARGIN // 2
    cx = rng.randint(rx + 12, CANVAS_W - rx - 12)
    box = (cx - rx, cy - ry, cx + rx, cy + ry)
    for p in scene.pumps:
        x0, y0, x1, y1 = p.module
        if not (box[2] < x0 or box[0] > x1 or box[3] < y0 or box[1] > y1):
            return None
    return (cx, cy, rx, ry)


def generate_scene(seed: str, cfg: dict[str, Any] | None = None) -> Scene:
    cfg = cfg or load_config()
    rng = random.Random(seed)
    n = rng.randint(cfg["pumps"]["min"], cfg["pumps"]["max"])
    # "cols" yields dials below the 70 px legibility floor (see check_layout), so only rows are generated.
    arrangement = "single" if n == 1 else "rows"
    pumps = [_sample_pump(rng, cfg, chr(ord("A") + i)) for i in range(n)]
    for p, rect in zip(pumps, module_rects(n, arrangement), strict=True):
        layout_pump(p, rect)
    scene = Scene(
        seed=seed,
        theme=rng.choice(cfg["themes"]),
        pumps=pumps,
        arrangement=arrangement,
        font_scale=rng.choice([0.95, 1.0, 1.05]),
    )
    return scene


def with_changes(scene: Scene, **kw: Any) -> Scene:
    return replace(scene, **kw)
