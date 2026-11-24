import { NextRequest } from "next/server";
import { serverConfig } from "@/lib/server/config";
import { IDEMPOTENCY_RE, resolveUpstream } from "@/lib/server/proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_BODY = 16 * 1024;

async function handle(req: NextRequest, ctx: { params: Promise<{ set: string; path: string[] }> }) {
  const { set, path } = await ctx.params;
  const base =
    set === "demo" ? serverConfig.demoApi : set === "factory" ? serverConfig.factoryApi : null;
  if (!base) return Response.json({ error: "unknown_dataset" }, { status: 404 });
  const up = resolveUpstream(req.method, path, req.nextUrl.searchParams);
  if (!up) return Response.json({ error: "not_found" }, { status: 404 });

  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (req.method === "POST") {
    const text = await req.text();
    if (text.length > MAX_BODY) return Response.json({ error: "body_too_large" }, { status: 413 });
    body = text || undefined;
    if (body) headers["content-type"] = "application/json";
    const key = req.headers.get("idempotency-key");
    if (key && IDEMPOTENCY_RE.test(key)) headers["idempotency-key"] = key;
  }
  if (up.needsAuth) {
    if (!serverConfig.revealToken) {
      return Response.json({ error: "reveal_token_not_configured" }, { status: 503 });
    }
    headers.authorization = `Bearer ${serverConfig.revealToken}`;
  }
  try {
    const res = await fetch(`${base}${up.path}`, {
      method: req.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const out = new Headers();
    for (const h of ["content-type", "cache-control", "x-content-type-options"]) {
      const v = res.headers.get(h);
      if (v) out.set(h, v);
    }
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return Response.json({ error: "api_unreachable" }, { status: 502 });
  }
}

export { handle as GET, handle as POST };
