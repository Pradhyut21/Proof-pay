# PanelProof record contracts

These Draft 2020-12 schemas define version `1.0.0` for Python, Rust, and TypeScript consumers. The examples are contract fixtures. The image path and image digest illustrate fields without bundling a benchmark image.

- `Scene` contains private generator inputs. Each pump has an inlet and outlet reading plus RUN and ALARM states.
- `PublicTask` restricts public records to version, opaque task ID, relative PNG path, question, public rules and response schema. Model requests use PNG bytes, question, public rules and response schema. IDs and paths stay with the application.
- `PrivateTask` stores reference answers, evidence regions, lineage, split and validation status. The artifact loader checks its SHA-256 digest against the actual image bytes.
- `Attempt` records one model outcome. Correct, incorrect and unscored statuses carry a parsed answer. Provider errors, invalid output and skipped attempts record the corresponding status and any available error detail.
- `Run` records the evaluation configuration, selected task IDs digest and offline demo status.

Wire readings use signed safe integers in thousandths of the displayed unit. Pressure conversion uses the ratios in `shared/units.json` and rounds the canonical milli-kPa result half away from zero. Numeric tolerances use thousandths of the reference answer's unit. Normalize before scoring. The rule threshold is inclusive at 300000 milli-kPa. The golden fixtures independently specify expected state and indicator consistency.

Use the Pydantic models at the Python worker boundary, the TypeScript guards at the web boundary, and Rust's typed readers at service boundaries. Scene pump IDs and labels must each be unique. Application validation verifies file integrity and artifact access.

Regenerate the JSON schemas from the repository root after changing the Python definitions.

```powershell
$env:PYTHONPATH = 'python/src'
python -m panelproof.schemas
```
