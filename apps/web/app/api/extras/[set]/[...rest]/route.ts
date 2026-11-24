import fs from "node:fs";
import path from "node:path";
import { NextRequest } from "next/server";
import { ID_RE, serverConfig } from "@/lib/server/config";
import { currentFactoryDir } from "@/lib/server/jobs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_BYTES = 5 * 1024 * 1024;

function readJsonl(file: string): Record<string, unknown>[] {
  try {
    if (fs.statSync(file).size > MAX_BYTES) return [];
    return fs
      .readFileSync(file, "utf8")
      .split("\n")
      .filter(Boolean)
      .map((l) => JSON.parse(l) as Record<string, unknown>);
  } catch {
    return [];
  }
}

/** Demo fixture files that sit beside the contract bundle: counterfactual pairs and DEMO ONLY model attempts. */
export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ set: string; rest: string[] }> },
) {
  const { set, rest } = await ctx.params;
  const dir =
    set === "demo" ? serverConfig.demoDir : set === "factory" ? currentFactoryDir() : undefined;
  if (set !== "demo" && set !== "factory")
    return Response.json({ error: "unknown_dataset" }, { status: 404 });
  if (!dir) return Response.json([]);
  if (rest.length === 1 && rest[0] === "pairs") {
    return Response.json(readJsonl(path.join(dir, "public", "pairs.jsonl")));
  }
  if (rest.length === 2 && rest[0] === "attempts" && rest[1] && ID_RE.test(rest[1])) {
    const id = rest[1];
    return Response.json(
      readJsonl(path.join(dir, "public", "model_attempts.jsonl")).filter((r) => r.task_id === id),
    );
  }
  return Response.json({ error: "not_found" }, { status: 404 });
}
