"""Fixed-point unit helpers for the generator, verifier and metrics.

All conversion arithmetic is delegated to the shared contract in ``rules.py`` (factors from
``shared/units.json``, round to nearest, ties away from zero), so every component agrees on one table.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from .rules import _pressure_factors, _rounded

round_half_away = _rounded


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def to_milli_kpa(value_milli: int, unit: str) -> int:
    return _rounded(Fraction(value_milli) * _pressure_factors()[unit])


def from_milli_kpa(mkpa: int, unit: str) -> int:
    return _rounded(Fraction(mkpa) / _pressure_factors()[unit])


def convert_milli(value_milli: int, src: str, dst: str) -> int:
    factors = _pressure_factors()
    return _rounded(Fraction(value_milli) * factors[src] / factors[dst])
