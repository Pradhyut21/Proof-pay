"""Rule helpers for the generator and verifier, delegating to the shared rule in ``rules.py``."""

from __future__ import annotations

from .rules import PUMP_RULE

THRESHOLD_MKPA = PUMP_RULE.threshold_milli_kpa


def pump_state(run: bool, inlet_mkpa: int, outlet_mkpa: int) -> str:
    return PUMP_RULE.state_for(run, outlet_mkpa - inlet_mkpa)


def expected_alarm(state: str) -> bool:
    """ALARM is expected to be lit exactly in LOW_PRESSURE."""
    return state == "LOW_PRESSURE"


def public_rules_text() -> str:
    return PUMP_RULE.public_text
