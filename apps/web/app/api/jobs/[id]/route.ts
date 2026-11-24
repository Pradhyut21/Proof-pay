import { NextRequest } from "next/server";
import { getJob } from "@/lib/server/jobs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const job = getJob(id);
  if (!job) return Response.json({ error: "job_not_found" }, { status: 404 });
  return Response.json(job);
}
