/** Typed projection of the shared PanelProof contract (schemas/*.json, schema 1.0.0). */

export type DatasetSet = "demo" | "factory";

export interface PublicTask {
  schema_version: string;
  task_id: string;
  image_path: string;
  question: string;
  public_rules: string;
  /** JSON Schema describing the tagged answer the task accepts. */
  response_schema: Record<string, unknown>;
}

export type Answer =
  | { kind: "category"; value: string }
  | { kind: "numeric"; value_milli: number; unit: string }
  | { kind: "set"; values: string[] };

/** What the form needs, derived from a task's response_schema. */
export type ResponseSpec =
  | { type: "category"; allowed: string[] }
  | { type: "numeric"; units: string[] }
  | { type: "unsupported" };

export interface TaskPage {
  items: PublicTask[];
  next_cursor?: string | null;
}

export interface AttemptResult {
  task_id: string;
  correct: boolean;
}

/** UI-level outcome: server verdict plus client-observed transport failures. */
export type DisplayOutcome = "correct" | "incorrect" | "invalid" | "timeout" | "offline";

export interface EvidenceRegion {
  instrument_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Reveal {
  task_id: string;
  answer: Answer;
  tolerance_milli: number | null;
  evidence_regions: EvidenceRegion[] | null;
  solver_version: string;
}

export interface Pair {
  pair_id: string;
  task_ids: [string, string];
}

export interface ModelAttempt {
  task_id: string;
  model: string;
  condition: string;
  status: "ok" | "parse_error" | "timeout" | "provider_error";
  response: Answer | null;
  label?: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "expired";
export type Difficulty = "easy" | "medium" | "hard";

export interface Job {
  job_id: string;
  status: JobStatus;
  error: string | null;
  task_ids: string[];
  reused: boolean;
}

export interface Health {
  status: string;
  schema_version?: string;
}

export const IMAGE_WIDTH = 1280;
export const IMAGE_HEIGHT = 960;
