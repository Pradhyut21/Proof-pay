# Offline model evaluation

The evaluation runner uses released public task records. It writes one `attempts.jsonl` row per selected task and a `run.json` manifest. The default `demo` adapter emits a fixed `NORMAL` answer. Its outputs are **DEMO ONLY** for testing the pipeline.

```sh
uv run --project python --python 3.11 --locked python -m panelproof.evaluate \
  --tasks data/demo/public/tasks.jsonl \
  --asset-root data/demo --condition C1 --dry-run
```

Remove `--dry-run` to write a run under `results/runs/`. C0 sends the question, public rules, and response schema. C1 also sends the bytes from the task PNG. The adapter gets only those four public fields. The runner refuses PNGs with metadata or unsupported chunks, oversized files, and paths outside the artifact root. The selection order is deterministic from `--seed` and public task IDs.

C3 substitutes verified visible readings for the image. Before evaluating or printing a C3 dry-run plan, the runner independently reads each unique selected PNG and joins the recovered observations to the entire task selection locally. A failed or ambiguous observation stops the whole C3 run before any request. C3 supplies the visible equipment label, INLET and OUTLET readings with their displayed units, and observed RUN and ALARM lamp states. The attempt prompt omits image bytes, task and scene IDs, pixel coordinates, uncertainties, and derived verdicts. The C3 plan and run record include a hash of the observations, and changed readings invalidate the request cache.

To preflight an already selected 50-task pilot, use its JSONL and image root with `--condition C3 --limit 50 --max-calls 50 --max-retries 0 --dry-run`. Check `selected`, `c3_verified_images`, and `c3_observations_sha256` before building the matched run plan.

Attempt rows distinguish an `unscored` parsed answer, an `invalid_response`, a `provider_error`, and a `skipped` task. Scoring is a separate operation with its own private reference input. To prepare the Rust scorer input, map each row to `{"task_id": ..., "answer": parsed_answer}` for one model and condition. Use a null answer for failures or skips. Only validated answer JSON is retained as raw output, with provider secrets checked before persistence. Invalid output bodies and raw transport errors are omitted.

The local SQLite cache reuses successful results across runs. A repeat run can reuse replies written to the cache by an interrupted run. Cache identity includes prompt version, condition, provider endpoint, model ID and declared revision, maximum output tokens, public prompt, and image hash. Live responses are cached when a revision has been declared and any revision reported by the provider agrees. Timestamps, run IDs, and latency describe the new attempt. Cached rows omit provider usage from the earlier request so it is not counted twice.

## Planning approved live runs

Use a local copy of `configs/models.yaml` with an account-accessible vision model ID. Provider keys are read from environment variables. The live adapters use the OpenAI-compatible Chat Completions and Anthropic Messages request shapes. [OpenAI Chat reference](https://developers.openai.com/api/reference/resources/chat) · [Anthropic Messages reference](https://platform.claude.com/docs/en/api/messages)

Use `--model NAME --config PATH --dry-run` to plan without credentials or network calls. The plan reports a task selection hash and request ceilings before and after applying the spending budget. Running the live plan requires `--allow-live`, a positive `--max-cost-usd`, and a conservative `--call-cost-ceiling-usd` supplied by the operator. Set `--max-calls` to limit requests. A retry consumes a new call and cost reservation. Requests run sequentially. The cost cap constrains estimated reservations for that run, while actual provider billing is unknown here. Provider usage is recorded when returned. Model access and billing require separate verification for each live evaluation.
