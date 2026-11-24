import { loadReportPage } from "@/lib/server/reports";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const query = new URL(request.url).searchParams;
  const kind = query.get("kind") ?? "report";
  if (kind !== "report" && kind !== "manifest") return new Response(null, { status: 404 });
  const data = await loadReportPage(query.get("run") ?? undefined);
  if (data.status !== "ready") return new Response(null, { status: 404 });
  const payload = kind === "manifest" ? data.report.provenance : data.report;
  if (!payload) return new Response(null, { status: 404 });
  return Response.json(payload, {
    headers: {
      "Cache-Control": "private, no-store",
      "Content-Disposition":
        'attachment; filename="panelproof-' + data.selected + "-" + kind + '.json"',
    },
  });
}
