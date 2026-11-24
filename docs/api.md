# Local API contract

Start with an accepted, local dataset bundle containing `public/tasks.jsonl`, `private/tasks.jsonl` and the referenced `images/*.png` paths. A private record and its public record share a task ID. The private record carries the expected SHA-256. Startup decodes the PNGs, checks evidence bounds and rejects metadata, corrupt images and dev/frozen overlap by group, base scene or exact image hash. Supply a distinct local SQLite database path.

```sh
cargo run -p panelproof-api -- path/to/dataset path/to/local.sqlite
```

The server binds to `127.0.0.1:3001` by default. An optional third argument changes the loopback address or port. Keep the service same-origin when wiring the frontend, for example with server-side proxy routes. For local judge review, set `PANELPROOF_REVEAL_TOKEN` to a fresh developer-supplied value of 16–128 visible ASCII characters before starting the service. Use it only in local development and never commit it.

| Method and path | Response and inputs |
| --- | --- |
| `GET /healthz` | Checks SQLite and returns `status` and `schema_version`. |
| `GET /api/v1/capabilities` | Returns local-import mode and flags for available features. |
| `GET /api/v1/tasks?cursor=&limit=` | Sorted public task records in `items` and optional `next_cursor`. Omit cursor for the first page. The default limit is 25 and the maximum is 100. |
| `GET /api/v1/tasks/{id}` | Public task record conforming to the [task schema](../schemas/task_public.schema.json). |
| `GET /api/v1/tasks/{id}/image` | SHA-256-checked PNG bytes. The ID selects a task already in the bundle. |
| `POST /api/v1/tasks/{id}/reveal` | For an authorized dev task, returns reference answer, tolerance, evidence regions and solver version. |
| `POST /api/v1/attempts` | Provide `task_id` and a tagged `answer`. Returns `task_id` and deterministic `correct` for an authorized dev task. |

Send `Authorization: Bearer <token>` to the two dev-only routes. Attempts also require an `Idempotency-Key` of 1–80 ASCII alphanumeric, hyphen or underscore characters beginning with a letter or digit. The first answer returns `201`. A byte-equivalent typed answer repeated with the same key returns `200`. A different answer with that key returns `409`. Frozen task answers stay private.

The generation and evaluation job routes, worker progress, metrics export and connected UI require the renderer, independently verified task packages and run integration.
