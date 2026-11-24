"""Deterministic rule evaluation for the supported fictional pump panel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Literal

from .schemas import Pressure, PressureUnit, Pump

PumpState = Literal["STOPPED", "NORMAL", "LOW_PRESSURE"]
AlarmConsistency = Literal["CONSISTENT", "CONTRADICTION"]


@lru_cache(maxsize=1)
def _pressure_factors() -> dict[str, Fraction]:
    source = Path(__file__).resolve().parents[3] / "shared" / "units.json"
    data = (
        source.read_text(encoding="utf-8")
        if source.is_file()
        else (files("panelproof").joinpath("units.json").read_text(encoding="utf-8"))
    )
    return {
        unit: Fraction(factor["numerator"], factor["denominator"])
        for unit, factor in json.loads(data)["pressure"].items()
    }


def _rounded(value: Fraction) -> int:
    quotient, remainder = divmod(abs(value.numerator), value.denominator)
    magnitude = quotient + int(2 * remainder >= value.denominator)
    return magnitude if value >= 0 else -magnitude


def convert_pressure(reading: Pressure, to_unit: PressureUnit) -> int:
    """Convert to thousandths of the target unit, with ties away from zero."""
    factors = _pressure_factors()
    return _rounded(reading.value_milli * factors[reading.unit] / factors[to_unit])


def conversion_rules_text() -> str:
    factors = _pressure_factors()
    statements = []
    for unit in ("bar", "psi"):
        factor = factors[unit]
        value = format(Decimal(factor.numerator) / Decimal(factor.denominator), "f")
        statements.append(f"1 {unit} = {value} kPa")
    return "Use " + " and ".join(statements) + "."


@dataclass(frozen=True)
class PumpResult:
    inlet_milli_kpa: int
    outlet_milli_kpa: int
    delta_milli_kpa: int
    state: PumpState
    consistency: AlarmConsistency


@dataclass(frozen=True)
class PumpRule:
    threshold_milli_kpa: int = 300_000

    @property
    def public_text(self) -> str:
        threshold = format(Decimal(self.threshold_milli_kpa) / 1000, "f")
        return (
            "For the named pump, RUN off means STOPPED. With RUN on, convert each "
            f"reading to kPa. {conversion_rules_text()} Round each to the nearest 0.001 kPa with ties away "
            "from zero. Subtract inlet pressure from outlet pressure. If the "
            f"difference is at least {threshold} kPa, the state is NORMAL. Otherwise "
            "it is LOW_PRESSURE. ALARM is expected to be on only for LOW_PRESSURE."
        )

    def solve(self, pump: Pump) -> PumpResult:
        inlet = convert_pressure(pump.inlet, "kPa")
        outlet = convert_pressure(pump.outlet, "kPa")
        delta = outlet - inlet
        state = self.state_for(pump.run, delta)
        consistency: AlarmConsistency = (
            "CONSISTENT" if pump.alarm == (state == "LOW_PRESSURE") else "CONTRADICTION"
        )
        return PumpResult(inlet, outlet, delta, state, consistency)

    def state_for(self, run: bool, delta_milli_kpa: int) -> PumpState:
        if not run:
            return "STOPPED"
        return "NORMAL" if delta_milli_kpa >= self.threshold_milli_kpa else "LOW_PRESSURE"

    def has_unique_state(self, pump: Pump, uncertainty_milli_kpa: int) -> bool:
        """Check whether the whole reading interval yields the same rule state."""
        if uncertainty_milli_kpa < 0:
            raise ValueError("uncertainty must be nonnegative")
        delta = self.solve(pump).delta_milli_kpa
        return self.state_for(pump.run, delta - uncertainty_milli_kpa) == self.state_for(
            pump.run, delta + uncertainty_milli_kpa
        )


PUMP_RULE = PumpRule()
