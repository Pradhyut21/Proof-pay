import { NextRequest } from "next/server";
import { startJob, validateJobInput } from "@/lib/server/jobs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const text = await req.text();
  if (text.length > 1024) return Response.json({ error: "body_too_large" }, { status: 413 });
  let input: unknown;
  try {
    input = JSON.parse(text);
  } catch {
    return Response.json({ error: "invalid_json" }, { status: 400 });
  }
  const v = validateJobInput(input);
  if (typeof v === "string") return Response.json({ error: v }, { status: 422 });
  const job = await startJob(v.seed, v.count, v.difficulty);
  return Response.json(job, { status: 202 });
}
