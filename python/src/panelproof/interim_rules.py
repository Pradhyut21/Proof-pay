"""Public fictional pump rules (INTERIM shim for #6, kept deliberately tiny).

Rule text is generated from RULE_DEFINITION so wording and logic cannot drift.
"""

from __future__ import annotations

RULE_DEFINITION = {
    "version": "1.0.0",
    "threshold_kpa": 300,
    "states": ["STOPPED", "NORMAL", "LOW_PRESSURE"],
    "alarm_expected_in": "LOW_PRESSURE",
}
THRESHOLD_MKPA = RULE_DEFINITION["threshold_kpa"] * 1000


def pump_state(run: bool, inlet_mkpa: int, outlet_mkpa: int) -> str:
    if not run:
        return "STOPPED"
    return "NORMAL" if outlet_mkpa - inlet_mkpa >= THRESHOLD_MKPA else "LOW_PRESSURE"


def expected_alarm(state: str) -> bool:
    return state == RULE_DEFINITION["alarm_expected_in"]


def public_rules_text() -> str:
    t = RULE_DEFINITION["threshold_kpa"]
    return (
        "Fictional operating rules. "
        "1) When RUN is off, the named pump is STOPPED. "
        "2) When RUN is on, convert inlet and outlet pressure to kPa and compute outlet minus inlet; "
        f"a difference of at least {t} kPa is NORMAL, otherwise LOW_PRESSURE. "
        "3) ALARM is expected to be on only in LOW_PRESSURE; a pump is CONSISTENT when its visible "
        "ALARM state matches that expectation, otherwise INCONSISTENT."
    )
