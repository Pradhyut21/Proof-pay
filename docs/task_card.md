# Task card

**What is evaluated.** Reading synthetic fictional pump panels and applying public rules.

**Public rules.** RUN off gives `STOPPED`. The task states which rule to apply when RUN is on. The pressure-difference rule gives `NORMAL` when outlet minus inlet is at least 300 kPa. The inlet-floor rule added in v0.4 gives `NORMAL` when the inlet is at least 150 kPa. Both give `LOW_PRESSURE` below their threshold. X consistency tasks use the pressure-difference rule and expect ALARM exactly in `LOW_PRESSURE`. Pressures convert using the factors in `shared/units.json`.

| Skill | Task | Answer |
| --- | --- | --- |
| R (reading) | A displayed pressure | Milli-units of the displayed unit, with a tolerance |
| C (conversion) | A displayed pressure in a requested unit | Milli-units of the requested unit |
| M (state) | Operating state of a pump | `STOPPED`, `NORMAL`, `LOW_PRESSURE` |
| X (consistency) | Whether the ALARM lamp agrees with the rules | `CONSISTENT`, `CONTRADICTION` |
| Diagnostic | Evidence removed from the panel | `INSUFFICIENT` (abstain) |

**Variants.** Semantic flips change the correct answer. The targeted inlet-floor crossing moves only the inlet needle and preserves the pressure-difference classification. Preserving edits (a unit change) keep the answer. Nuisance edits (theme, position) keep it. Missing-evidence edits remove what is needed.

**Answer format.** Each public task includes a JSON-Schema `response_schema`. Numeric answers are integer milli-units; scoring compares them within the private tolerance.

**Out of scope.** Real instruments, photographs, safety decisions or any claim about real equipment. All data is fictional and generated.

**Known limits.** The v0.4 configuration covers three layouts. C tasks ask for the outlet pressure only. Production verification covers clean synthetic renders. Human review is pending. [Validation](validation.md)
