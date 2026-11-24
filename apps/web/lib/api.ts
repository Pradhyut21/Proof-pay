import type {
  AttemptResult,
  Capabilities,
  Difficulty,
  Health,
  Job,
  ModelAttemptsResponse,
  Pair,
  PublicTask,
  Reveal,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_PP_API ?? "http://127.0.0.1:8787";
const REVEAL_TOKEN = process.env.NEXT_PUBLIC_PP_REVEAL_TOKEN ?? "local-dev";

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
    const res = await fetch(`${API_BASE}${path}`, { ...init, signal: ctl.signal });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { error?: string };
        detail = body.error ?? detail;
      } catch {
        /* keep status text */
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

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const imageUrl = (imagePath: string): string =>
  `${API_BASE}/v1/images/${imagePath.split("/").pop() ?? ""}`;

export const api = {
  health: () => request<Health>("/health"),
  capabilities: () => request<Capabilities>("/v1/capabilities"),
  listTasks: () => request<PublicTask[]>("/v1/tasks"),
  getTask: (id: string) => request<PublicTask>(`/v1/tasks/${encodeURIComponent(id)}`),
  listPairs: () => request<Pair[]>("/v1/arena/pairs"),
  modelAttempts: (id: string) =>
    request<ModelAttemptsResponse>(`/v1/tasks/${encodeURIComponent(id)}/model-attempts`),
  postAttempt: (taskId: string, response: unknown) =>
    request<AttemptResult>("/v1/attempts", json({ task_id: taskId, response })),
  reveal: (id: string) =>
    request<Reveal>(`/v1/tasks/${encodeURIComponent(id)}/reveal`, {
      method: "POST",
      headers: { "x-panelproof-token": REVEAL_TOKEN },
    }),
  startJob: (seed: string, count: number, difficulty: Difficulty) =>
    request<Job>("/v1/jobs/generate", json({ seed, count, difficulty })),
  getJob: (id: string) => request<Job>(`/v1/jobs/${encodeURIComponent(id)}`),
};
