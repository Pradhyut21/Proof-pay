# PanelProof run report - DEMO ONLY - mock outputs, not a measurement

> **DEMO ONLY.** These outputs come from the offline mock adapter. They demonstrate the report format and must not be cited as model performance.

## Model `demo-offline-mock`

Matched tasks: 68 (selection hash `ef633b3c9f15b8bf`); tasks missing a condition: {'C0': 0, 'C1': 0, 'C3': 0}

| Cond | attempted | completed | valid | correct | valid-only acc | all-attempt acc (95% CI) | failures |
|---|---|---|---|---|---|---|---|
| C0 | 68 | 61 | 61 | 15 | 0.2459 (n=61) | 0.2206 (n=68; 0.1507-0.3051, 8 groups, 1000 reps, seed 20261124) | {'parse_error': 6, 'timeout': 1} |
| C1 | 68 | 67 | 67 | 62 | 0.9254 (n=67) | 0.9118 (n=68; 0.8488-1.0, 8 groups, 1000 reps, seed 20261124) | {'parse_error': 1} |
| C3 | 68 | 68 | 68 | 66 | 0.9706 (n=68) | 0.9706 (n=68; 0.9359-1.0, 8 groups, 1000 reps, seed 20261124) | {} |

Grounding gain C1-C0: **0.6912** on 68 matched tasks (0.6056 to 0.7778, 8 groups).

### C0 detail

| skill | valid | correct | valid-only | all-attempt |
|---|---|---|---|---|
| C | 2 | 0 | 0.0 | 0.0 |
| M | 30 | 5 | 0.1667 | 0.1471 |
| R | 11 | 0 | 0.0 | 0.0 |
| X | 18 | 10 | 0.5556 | 0.4762 |

| difficulty | valid | correct | valid-only | all-attempt |
|---|---|---|---|---|
| easy | 24 | 5 | 0.2083 | 0.1852 |
| medium | 20 | 5 | 0.25 | 0.2273 |
| hard | 17 | 5 | 0.2941 | 0.2632 |

Pairs - semantic: 14 (pair correctness 0.2143, directional sensitivity 0.3333); nuisance: 4 (pair correctness 0.0, invariance 0.0); preserving: 1 (both-correct 0).
Worst-group accuracy 0.0769 over 8 groups; all-variants-correct 0.
Latency {'mean': 742.4, 'p95': 1164.1}; cost USD 0.0; cache-hit rate 0.0882.

### C1 detail

| skill | valid | correct | valid-only | all-attempt |
|---|---|---|---|---|
| C | 2 | 2 | 1.0 | 1.0 |
| M | 34 | 31 | 0.9118 | 0.9118 |
| R | 11 | 9 | 0.8182 | 0.8182 |
| X | 20 | 20 | 1.0 | 0.9524 |

| difficulty | valid | correct | valid-only | all-attempt |
|---|---|---|---|---|
| easy | 27 | 25 | 0.9259 | 0.9259 |
| medium | 22 | 22 | 1.0 | 1.0 |
| hard | 18 | 15 | 0.8333 | 0.7895 |

Pairs - semantic: 14 (pair correctness 0.8571, directional sensitivity 0.8571); nuisance: 4 (pair correctness 1.0, invariance 1.0); preserving: 1 (both-correct 1).
Worst-group accuracy 0.7692 over 8 groups; all-variants-correct 5.
Latency {'mean': 728.9, 'p95': 1152.3}; cost USD 0.0; cache-hit rate 0.0441.

### C3 detail

| skill | valid | correct | valid-only | all-attempt |
|---|---|---|---|---|
| C | 2 | 2 | 1.0 | 1.0 |
| M | 34 | 32 | 0.9412 | 0.9412 |
| R | 11 | 11 | 1.0 | 1.0 |
| X | 21 | 21 | 1.0 | 1.0 |

| difficulty | valid | correct | valid-only | all-attempt |
|---|---|---|---|---|
| easy | 27 | 26 | 0.963 | 0.963 |
| medium | 22 | 22 | 1.0 | 1.0 |
| hard | 19 | 18 | 0.9474 | 0.9474 |

Pairs - semantic: 14 (pair correctness 0.9286, directional sensitivity 1.0); nuisance: 4 (pair correctness 1.0, invariance 1.0); preserving: 1 (both-correct 1).
Worst-group accuracy 0.875 over 8 groups; all-variants-correct 6.
Latency {'mean': 768.5, 'p95': 1149.5}; cost USD 0.0; cache-hit rate 0.1912.

## Interpretation limits

- Intervals are base-group cluster bootstraps; groups are not independent draws from a wider population.
- C3 supplies verified readings as text and therefore isolates rule reasoning; it is not a vision score.
- Missing responses are excluded from the matched set and listed separately; they are never counted as correct.
- The missing-evidence diagnostic set is reported separately and is not part of these aggregates.
