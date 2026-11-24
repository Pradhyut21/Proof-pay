"""Measure whether an irrelevant ALARM cue predicts a reference label."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from math import log2

from .rules import PUMP_RULE
from .schemas import Pump


@dataclass(frozen=True)
class BalanceAudit:
    samples: int
    expected_displayed: dict[tuple[bool, bool], int]
    operating_states: dict[str, int]
    consistency_labels: dict[str, int]
    lamp_state_mutual_information: float
    lamp_consistency_mutual_information: float


def _mutual_information(joint: Counter[tuple[bool, str]]) -> float:
    total = joint.total()
    if total == 0:
        return 0.0
    left: Counter[bool] = Counter()
    right: Counter[str] = Counter()
    for (cue, outcome), count in joint.items():
        left[cue] += count
        right[outcome] += count
    return sum(
        count / total * log2(count * total / (left[cue] * right[outcome]))
        for (cue, outcome), count in joint.items()
    )


def audit_alarm_balance(pumps: Iterable[Pump]) -> BalanceAudit:
    crosses = Counter({(False, False): 0, (False, True): 0, (True, False): 0, (True, True): 0})
    states: Counter[str] = Counter()
    consistency: Counter[str] = Counter()
    lamp_states: Counter[tuple[bool, str]] = Counter()
    lamp_consistency: Counter[tuple[bool, str]] = Counter()
    for pump in pumps:
        answer = PUMP_RULE.solve(pump)
        crosses[answer.state == "LOW_PRESSURE", pump.alarm] += 1
        states[answer.state] += 1
        consistency[answer.consistency] += 1
        lamp_states[pump.alarm, answer.state] += 1
        lamp_consistency[pump.alarm, answer.consistency] += 1
    return BalanceAudit(
        samples=crosses.total(),
        expected_displayed=dict(crosses),
        operating_states=dict(states),
        consistency_labels=dict(consistency),
        lamp_state_mutual_information=_mutual_information(lamp_states),
        lamp_consistency_mutual_information=_mutual_information(lamp_consistency),
    )
