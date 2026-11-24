import { ID_RE } from "./config";

export interface Upstream {
  path: string;
  /** Dev-only routes need the bearer token, added server-side. */
  needsAuth: boolean;
}

/**
 * Map a proxied request to an upstream Axum path, or null if it is not on the allow-list.
 * Only the documented local-API routes are reachable; ids are validated before they are interpolated.
 */
export function resolveUpstream(
  method: string,
  segments: string[],
  search: URLSearchParams,
): Upstream | null {
  const [a, b, c, id, tail, extra] = segments;
  if (method === "GET" && segments.length === 1 && a === "healthz")
    return { path: "/healthz", needsAuth: false };
  if (a !== "api" || b !== "v1") return null;
  if (method === "GET" && c === "capabilities" && segments.length === 3) {
    return { path: "/api/v1/capabilities", needsAuth: false };
  }
  if (method === "GET" && c === "tasks" && segments.length === 3) {
    const q = new URLSearchParams();
    const limit = search.get("limit");
    const cursor = search.get("cursor");
    if (limit && /^\d{1,3}$/.test(limit)) q.set("limit", limit);
    if (cursor && ID_RE.test(cursor)) q.set("cursor", cursor);
    const qs = q.toString();
    return { path: `/api/v1/tasks${qs ? `?${qs}` : ""}`, needsAuth: false };
  }
  if (c === "tasks" && id && ID_RE.test(id) && extra === undefined) {
    if (method === "GET" && tail === undefined)
      return { path: `/api/v1/tasks/${id}`, needsAuth: false };
    if (method === "GET" && tail === "image")
      return { path: `/api/v1/tasks/${id}/image`, needsAuth: false };
    if (method === "POST" && tail === "reveal")
      return { path: `/api/v1/tasks/${id}/reveal`, needsAuth: true };
  }
  if (method === "POST" && c === "attempts" && segments.length === 3) {
    return { path: "/api/v1/attempts", needsAuth: true };
  }
  return null;
}

export const IDEMPOTENCY_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
