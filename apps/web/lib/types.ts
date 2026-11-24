/** Typed projection of the local API contract (schema 1.0.0). Public types never carry answers. */

export type ResponseSchema =
  | { type: "category"; allowed: string[] }
  | { type: "numeric"; unit: string; scale: "milli"; note?: string };

export interface PublicTask {
  schema_version: string;
  task_id: string;
  image: string;
  question: string;
  rules: string;
  response_schema: ResponseSchema;
  set: string;
}

export type Answer =
  | { kind: "category"; value: string }
  | { kind: "numeric"; value_milli: number; unit: string; tolerance_milli?: number };

export type AttemptOutcome = "correct" | "incorrect" | "invalid";
/** UI-level outcome: server outcomes plus client-observed transport failures. */
export type DisplayOutcome = AttemptOutcome | "timeout" | "offline";

export interface AttemptResult {
  attempt_id: string;
  task_id: string;
  outcome: AttemptOutcome;
  status: "ok";
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
  latency_ms?: number;
}

export interface ModelAttemptsResponse {
  task_id: string;
  label: string;
  attempts: ModelAttempt[];
}

export interface EvidenceBox {
  pump: string;
  kind: string;
  box: [number, number, number, number];
  needle_tip?: [number, number];
}

export interface Reveal {
  task_id: string;
  answer: Answer;
  variant_kind?: string | null;
  skill?: string;
  kind?: string;
  evidence?: EvidenceBox[];
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type Difficulty = "easy" | "medium" | "hard";

export interface Job {
  job_id: string;
  status: JobStatus;
  error: string | null;
  task_ids: string[];
  duplicate_of_existing: boolean;
}

export interface Health {
  status: string;
  service: string;
  version: string;
  tasks_loaded: number;
}

export interface Capabilities {
  schema_version: string;
  conditions: string[];
  offline_demo: boolean;
  live_models: boolean;
  reveal_enabled: boolean;
  generation: { max_count: number; deadline_seconds: number };
}

export const IMAGE_WIDTH = 1280;
export const IMAGE_HEIGHT = 960;
