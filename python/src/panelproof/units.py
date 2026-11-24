"""Fixed-point unit conversion (INTERIM shim for #4; reads shared/units.json)."""

from __future__ import annotations

import json
from fractions import Fraction
from functools import lru_cache
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def unit_table() -> dict[str, Fraction]:
    raw = json.loads((repo_root() / "shared" / "units.json").read_text(encoding="utf-8"))
    return {k: Fraction(v["num"], v["den"]) for k, v in raw["units"].items()}


def round_half_away(x: Fraction) -> int:
    """Round to nearest integer, ties away from zero."""
    n, d = x.numerator, x.denominator
    q, r = divmod(abs(n) * 2 + d, d * 2)
    return q if n >= 0 else -q


def to_milli_kpa(value_milli: int, unit: str) -> int:
    return round_half_away(Fraction(value_milli) * unit_table()[unit])


def from_milli_kpa(mkpa: int, unit: str) -> int:
    return round_half_away(Fraction(mkpa) / unit_table()[unit])


def convert_milli(value_milli: int, src: str, dst: str) -> int:
    return round_half_away(Fraction(value_milli) * unit_table()[src] / unit_table()[dst])
