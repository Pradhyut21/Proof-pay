import { formatAnswer } from "@/lib/answers";
import type { DisplayOutcome, ModelAttempt } from "@/lib/types";
import { OutcomeBadge } from "./OutcomeBadge";

/** Up to three model attempts. Offline demo rows are always labelled DEMO ONLY. */
export function ModelAttempts({
  attempts,
  correctAnswer,
  offline,
}: {
  attempts: ModelAttempt[];
  correctAnswer?: string;
  offline?: boolean;
}) {
  if (offline) {
    return (
      <p data-testid="model-offline">
        <OutcomeBadge outcome="offline" /> Model results are unavailable because the API is offline.
      </p>
    );
  }
  const rows = attempts.slice(0, 3);
  if (rows.length === 0)
    return <p className="text-sm text-muted-foreground">No model attempts for this task.</p>;
  return (
    <div className="space-y-2" data-testid="model-attempts">
      <p className="rounded-md border-2 border-warning px-2 py-1 text-sm font-bold text-warning">
        DEMO ONLY: simulated offline outputs, not a measurement of any real model.
      </p>
      <ul className="space-y-1">
        {rows.map((a) => {
          const shown = a.response ? formatAnswer(a.response) : "no usable answer";
          let outcome: DisplayOutcome | undefined;
          if (a.status === "timeout") outcome = "timeout";
          else if (a.status !== "ok") outcome = "invalid";
          else if (correctAnswer !== undefined)
            outcome = shown === correctAnswer ? "correct" : "incorrect";
          return (
            <li key={a.model} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono font-semibold">{a.model}</span>
              <span>answered: {shown}</span>
              {outcome ? <OutcomeBadge outcome={outcome} /> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
