# Task card

**What is evaluated.** Reading synthetic fictional pump panels and applying public rules.

**Public rules.** RUN lamp off: `STOPPED`. RUN on: outlet minus inlet at least 300 kPa is `NORMAL`, otherwise `LOW_PRESSURE`. The ALARM lamp is expected exactly in `LOW_PRESSURE`. Pressures use kPa, bar, psi or MPa and convert with the factors in `shared/units.json` (psi is 6.894757293168 kPa).

| Skill | Task | Answer |
| --- | --- | --- |
| R (reading) | A displayed pressure | Milli-units of the displayed unit, with a tolerance |
| C (conversion) | A displayed pressure in a requested unit | Milli-units of the requested unit |
| M (state) | Operating state of a pump | `STOPPED`, `NORMAL`, `LOW_PRESSURE` |
| X (consistency) | Whether the ALARM lamp agrees with the rules | `CONSISTENT`, `CONTRADICTION` |
| Diagnostic | Evidence removed from the panel | `INSUFFICIENT` (abstain) |

**Variants.** Semantic flips change the correct answer. Preserving edits (a unit change) keep it. Nuisance edits (theme, position) keep it. Missing-evidence edits remove what is needed.

**Answer format.** Each public task includes a JSON-Schema `response_schema`. Numeric answers are integer milli-units; scoring compares them within the private tolerance.

**Out of scope.** Real instruments, photographs, safety decisions or any claim about real equipment. All data is fictional and generated.

**Known limits.** Two layout families. C tasks ask for the outlet pressure only. Verifier acceptance under image corruption is limited (see [`validation.md`](validation.md)). No human has reviewed the tasks.
