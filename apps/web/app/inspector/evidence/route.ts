import type { NextRequest } from "next/server";
import { POST as revealProxy } from "@/app/api/pp/[set]/[...path]/route";
import { ID_RE, serverConfig } from "@/lib/server/config";
import { currentFactoryDir } from "@/lib/server/jobs";
import { parseReference } from "../model";
import { readRasterEvidence } from "./bundle";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const headers = { "Cache-Control": "no-store" };

function errorResponse(error: string, status: number) {
  return Response.json({ error }, { status, headers });
}

export async function POST(req: NextRequest) {
  const set = req.nextUrl.searchParams.get("set");
  const taskId = req.nextUrl.searchParams.get("task");
  const job = req.nextUrl.searchParams.get("job") ?? "";
  if ((set !== "demo" && set !== "factory") || !taskId || !ID_RE.test(taskId)) {
    return errorResponse("inspector_task_unavailable", 404);
  }

  const directory = set === "demo" ? serverConfig.demoDir : currentFactoryDir(job);
  if (!directory) return errorResponse("inspector_factory_expired", 410);

  const upstream = await revealProxy(req, {
    params: Promise.resolve({ set, path: ["api", "v1", "tasks", taskId, "reveal"] }),
  });
  if (!upstream.ok) {
    await upstream.body?.cancel();
    return errorResponse("inspector_reveal_unavailable", upstream.status);
  }

  let body: unknown;
  try {
    body = await upstream.json();
  } catch {
    return errorResponse("inspector_reference_invalid", 502);
  }
  const reference = parseReference(body, taskId);
  if (!reference) return errorResponse("inspector_reference_invalid", 502);

  if (set === "factory" && currentFactoryDir(job) !== directory) {
    return errorResponse("inspector_factory_expired", 410);
  }
  const raster = await readRasterEvidence(directory, reference);
  if (set === "factory" && currentFactoryDir(job) !== directory) {
    return errorResponse("inspector_factory_expired", 410);
  }

  return Response.json({ reference, raster }, { headers });
}
