"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { buildResponse } from "@/lib/answers";
import type { DisplayOutcome, PublicTask } from "@/lib/types";
import { OutcomeBadge } from "./OutcomeBadge";

interface Props {
  task: PublicTask;
  onResult?: (outcome: DisplayOutcome) => void;
}

/** Shows the public question + rules and submits one human attempt through the backend. */
export function QuestionForm({ task, onResult }: Props) {
  const uid = useId();
  const [category, setCategory] = useState<string>();
  const [numeric, setNumeric] = useState("");
  const [error, setError] = useState<string>();
  const [outcome, setOutcome] = useState<DisplayOutcome>();
  const [busy, setBusy] = useState(false);
  const schema = task.response_schema;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(undefined);
    const built = buildResponse(schema, { category, numeric });
    if (!built.ok) {
      setError(built.message);
      return;
    }
    setBusy(true);
    let result: DisplayOutcome;
    try {
      result = (await api.postAttempt(task.task_id, built.response)).outcome;
    } catch (err) {
      result = err instanceof ApiError && err.kind === "timeout" ? "timeout" : "offline";
    }
    setBusy(false);
    setOutcome(result);
    onResult?.(result);
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-labelledby={`${uid}-q`} noValidate>
      <p id={`${uid}-q`} className="text-base font-semibold">
        {task.question}
      </p>
      <details className="rounded-md border border-border p-2 text-sm">
        <summary className="min-h-11 cursor-pointer font-semibold leading-[2.75rem]">
          Public rules
        </summary>
        <p className="pb-1 text-muted-foreground">{task.rules}</p>
      </details>
      {schema.type === "category" ? (
        <fieldset className="space-y-1">
          <legend className="text-sm font-semibold">Your answer</legend>
          {schema.allowed.map((opt) => (
            <label key={opt} className="flex min-h-11 items-center gap-2">
              <input
                type="radio"
                name={`${uid}-cat`}
                value={opt}
                checked={category === opt}
                onChange={() => setCategory(opt)}
                className="h-5 w-5"
              />
              {opt}
            </label>
          ))}
        </fieldset>
      ) : (
        <div className="space-y-1">
          <label htmlFor={`${uid}-num`} className="text-sm font-semibold">
            Your answer ({schema.unit})
          </label>
          <input
            id={`${uid}-num`}
            inputMode="decimal"
            value={numeric}
            onChange={(ev) => setNumeric(ev.target.value)}
            aria-describedby={error ? `${uid}-err` : undefined}
            aria-invalid={error ? true : undefined}
            className="block min-h-11 w-full rounded-md border border-border bg-background px-3"
          />
        </div>
      )}
      {error ? (
        <p id={`${uid}-err`} role="alert" className="text-sm font-semibold text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy}>
          {busy ? "Scoring…" : "Submit answer"}
        </Button>
        <div aria-live="polite">{outcome ? <OutcomeBadge outcome={outcome} /> : null}</div>
      </div>
    </form>
  );
}
