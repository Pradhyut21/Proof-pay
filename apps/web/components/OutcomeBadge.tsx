import type { DisplayOutcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAP: Record<DisplayOutcome, { icon: string; text: string; cls: string }> = {
  correct: { icon: "✓", text: "Correct", cls: "border-success text-success" },
  incorrect: { icon: "✕", text: "Incorrect", cls: "border-danger text-danger" },
  invalid: { icon: "⚠", text: "Invalid answer", cls: "border-warning text-warning" },
  timeout: { icon: "⏱", text: "Timed out", cls: "border-warning text-warning" },
  offline: { icon: "⛔", text: "Offline", cls: "border-border text-muted-foreground" },
};

/** Status is conveyed by an icon and words as well as colour. */
export function OutcomeBadge({ outcome }: { outcome: DisplayOutcome }) {
  const m = MAP[outcome];
  return (
    <span
      data-testid={`outcome-${outcome}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border-2 px-2 py-1 text-sm font-bold",
        m.cls,
      )}
    >
      <span aria-hidden="true">{m.icon}</span>
      {m.text}
    </span>
  );
}
