import type {
  Answer,
  AttemptResult,
  DatasetSet,
  Difficulty,
  Job,
  ModelAttempt,
  Pair,
  PublicTask,
  Reveal,
  TaskPage,
} from "./types";

/**
 * All calls are same-origin: `/api/pp/<set>/...` is a server-side proxy to the local Axum API (it adds the
 * dev-only bearer token, so the token never reaches the browser); `/api/jobs` and `/api/extras` are small
 * server routes for the generation worker and the demo fixture files.
 */
export type ApiErrorKind = "offline" | "timeout" | "http";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: ApiErrorKind,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 8000): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(path, { ...init, signal: ctl.signal, cache: "no-store" });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { error?: string };
        detail = body.error ?? detail;
      } catch {
        /* keep status text */
      }
      // 502/503 from the proxy means the upstream API is not running.
      if (res.status === 502 || res.status === 503) {
        throw new ApiError(detail, "offline", res.status);
      }
      throw new ApiError(detail, "http", res.status);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError("The request timed out", "timeout");
    }
    throw new ApiError("The local API is not reachable", "offline");
  } finally {
    clearTimeout(timer);
  }
}

const pp = (set: DatasetSet, p: string) => `/api/pp/${set}/${p}`;

export const imageUrl = (set: DatasetSet, taskId: string): string =>
  pp(set, `api/v1/tasks/${encodeURIComponent(taskId)}/image`);

function newKey(): string {
  const rand =
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `h-${rand}`.slice(0, 80);
}

const jsonHeaders = { "content-type": "application/json" };

export const api = {
  health: (set: DatasetSet = "demo") => request<{ status: string }>(pp(set, "healthz")),
  listTasks: (set: DatasetSet, cursor?: string) =>
    request<TaskPage>(
      pp(set, `api/v1/tasks?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
    ),
  getTask: (set: DatasetSet, id: string) =>
    request<PublicTask>(pp(set, `api/v1/tasks/${encodeURIComponent(id)}`)),
  postAttempt: (set: DatasetSet, taskId: string, answer: Answer) =>
    request<AttemptResult>(pp(set, "api/v1/attempts"), {
      method: "POST",
      headers: { ...jsonHeaders, "idempotency-key": newKey() },
      body: JSON.stringify({ task_id: taskId, answer }),
    }),
  reveal: (set: DatasetSet, id: string) =>
    request<Reveal>(pp(set, `api/v1/tasks/${encodeURIComponent(id)}/reveal`), {
      method: "POST",
    }),
  listPairs: (set: DatasetSet) => request<Pair[]>(`/api/extras/${set}/pairs`),
  modelAttempts: (set: DatasetSet, taskId: string) =>
    request<ModelAttempt[]>(`/api/extras/${set}/attempts/${encodeURIComponent(taskId)}`),
  startJob: (seed: string, count: number, difficulty: Difficulty) =>
    request<Job>(
      "/api/jobs",
      { method: "POST", headers: jsonHeaders, body: JSON.stringify({ seed, count, difficulty }) },
      15000,
    ),
  getJob: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
};
