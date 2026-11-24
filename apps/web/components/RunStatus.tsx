import type { JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABEL: Record<JobStatus, { icon: string; text: string; cls: string }> = {
  queued: { icon: "…", text: "Queued", cls: "border-border text-muted-foreground" },
  running: { icon: "↻", text: "Running", cls: "border-primary text-primary" },
  succeeded: { icon: "✓", text: "Succeeded", cls: "border-success text-success" },
  failed: { icon: "✕", text: "Failed", cls: "border-danger text-danger" },
};

export function RunStatus({ status, error }: { status: JobStatus; error?: string | null }) {
  const m = LABEL[status];
  return (
    <div role="status" aria-live="polite" data-testid="run-status" className="space-y-1">
      <span
        className={cn(
          "inline-flex items-center gap-2 rounded-md border-2 px-2 py-1 text-sm font-bold",
          m.cls,
        )}
      >
        <span
          aria-hidden="true"
          className={status === "running" ? "inline-block motion-safe:animate-spin" : undefined}
        >
          {m.icon}
        </span>
        Job {m.text}
      </span>
      {status === "failed" && error ? <p className="text-sm text-danger">{error}</p> : null}
    </div>
  );
}
