"use client";

import { useId, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { buildAnswer, specFromSchema } from "@/lib/answers";
import type { DatasetSet, DisplayOutcome, PublicTask } from "@/lib/types";
import { OutcomeBadge } from "./OutcomeBadge";

interface Props {
  set: DatasetSet;
  task: PublicTask;
  job?: string;
  onResult?: (outcome: DisplayOutcome) => void;
}

/** Shows the public question + rules and submits one human attempt through the backend. */
export function QuestionForm({ set, task, onResult, job }: Props) {
  const uid = useId();
  const spec = useMemo(() => specFromSchema(task.response_schema), [task.response_schema]);
  const [category, setCategory] = useState<string>();
  const [numeric, setNumeric] = useState("");
  const [unit, setUnit] = useState<string>();
  const [error, setError] = useState<string>();
  const [outcome, setOutcome] = useState<DisplayOutcome>();
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(undefined);
    const built = buildAnswer(spec, { category, numeric, unit });
    if (!built.ok) {
      setError(built.message);
      return;
    }
    setBusy(true);
    let result: DisplayOutcome | undefined;
    try {
      const r = await api.postAttempt(set, task.task_id, built.answer, job);
      result = r.correct ? "correct" : "incorrect";
    } catch (err) {
      if (err instanceof ApiError && err.kind === "timeout") result = "timeout";
      else if (err instanceof ApiError && err.kind === "http" && err.status === 422)
        result = "invalid";
      else if (err instanceof ApiError && err.kind === "http") {
        setError(`The server refused this attempt (${err.message}).`);
      } else result = "offline";
    }
    setBusy(false);
    setOutcome(result);
    if (result) onResult?.(result);
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
        <p className="pb-1 text-muted-foreground">{task.public_rules}</p>
      </details>
      {spec.type === "category" ? (
        <fieldset className="space-y-1">
          <legend className="text-sm font-semibold">Your answer</legend>
          {spec.allowed.map((opt) => (
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
      ) : spec.type === "numeric" ? (
        <div className="space-y-1">
          <label htmlFor={`${uid}-num`} className="text-sm font-semibold">
            Your answer (a number in the unit chosen beside it)
          </label>
          <div className="flex gap-2">
            <input
              id={`${uid}-num`}
              inputMode="decimal"
              value={numeric}
              onChange={(ev) => setNumeric(ev.target.value)}
              aria-describedby={error ? `${uid}-err` : undefined}
              aria-invalid={error ? true : undefined}
              className="block min-h-11 w-full rounded-md border border-border bg-background px-3"
            />
            <select
              aria-label="Unit"
              value={unit ?? spec.units[0]}
              onChange={(ev) => setUnit(ev.target.value)}
              className="min-h-11 rounded-md border border-border bg-background px-2"
            >
              {spec.units.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </div>
        </div>
      ) : (
        <p role="alert" className="text-sm font-semibold text-danger">
          This answer format is not supported by the form.
        </p>
      )}
      {error ? (
        <p id={`${uid}-err`} role="alert" className="text-sm font-semibold text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy || spec.type === "unsupported"}>
          {busy ? "Scoring…" : "Submit answer"}
        </Button>
        <div aria-live="polite">{outcome ? <OutcomeBadge outcome={outcome} /> : null}</div>
      </div>
    </form>
  );
}
