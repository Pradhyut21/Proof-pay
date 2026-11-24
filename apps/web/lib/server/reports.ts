import { lstat, readFile, readdir, realpath } from "node:fs/promises";
import path from "node:path";
import { parseRunReport, type RunReport } from "@/lib/report-data";
import { ID_RE, serverConfig } from "@/lib/server/config";

const MAX_REPORT_BYTES = 8 * 1024 * 1024;
const CURRENT = "current";
const REPORT_FILE = "report.json";

export type ReportSource = { id: string; label: string };
export type ReportPageData =
  | { status: "ready"; sources: ReportSource[]; selected: string; report: RunReport }
  | { status: "empty" | "offline" | "invalid" | "missing" };

function configuredReportsRoot(): string {
  const local = process.env.PANELPROOF_REPORT_ROOT?.trim();
  return path.resolve(serverConfig.root, local || path.join("data", "build", "demo_report"));
}

function notFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}

async function isReportFile(directory: string): Promise<boolean> {
  try {
    return (await lstat(path.join(directory, REPORT_FILE))).isFile();
  } catch (error) {
    if (notFound(error)) return false;
    throw error;
  }
}

function isPrivatePath(candidate: string): boolean {
  return candidate.split(/[/\\]/).some((part) => part.toLowerCase() === "private");
}

/** A server-selected root exposes only aggregate report.json artifacts, never arbitrary paths. */
export async function loadReportPage(
  runId?: string,
  configuredRoot = configuredReportsRoot(),
): Promise<ReportPageData> {
  if (runId !== undefined && !ID_RE.test(runId)) return { status: "missing" };
  let root: string;
  let sources: ReportSource[];
  try {
    root = await realpath(configuredRoot);
    if (isPrivatePath(root)) return { status: "offline" };
    const entries = await readdir(root, { withFileTypes: true });
    const namedRuns = entries
      .filter(
        (entry) =>
          entry.isDirectory() &&
          entry.name !== CURRENT &&
          ID_RE.test(entry.name) &&
          !isPrivatePath(entry.name),
      )
      .map((entry) => entry.name)
      .sort();
    const existing = await Promise.all(
      namedRuns.map((name) => isReportFile(path.join(root, name))),
    );
    sources = namedRuns.flatMap((id, i) => (existing[i] ? [{ id, label: id }] : []));
    if (await isReportFile(root)) sources.unshift({ id: CURRENT, label: "Local report" });
  } catch (error) {
    return { status: notFound(error) ? "empty" : "offline" };
  }
  const first = sources[0];
  if (!first) return { status: "empty" };
  const selected = runId ?? first.id;
  if (!sources.some((source) => source.id === selected)) return { status: "missing" };
  try {
    const directory = selected === CURRENT ? root : path.join(root, selected);
    const candidate = await realpath(path.join(directory, REPORT_FILE));
    const relative = path.relative(root, candidate);
    if (
      relative !== path.relative(root, path.join(directory, REPORT_FILE)) ||
      isPrivatePath(candidate)
    ) {
      return { status: "missing" };
    }
    const info = await lstat(candidate);
    if (!info.isFile() || info.size > MAX_REPORT_BYTES) return { status: "invalid" };
    const content = await readFile(candidate, "utf8");
    const report = parseRunReport(JSON.parse(content));
    return { status: "ready", sources, selected, report };
  } catch (error) {
    return { status: notFound(error) ? "missing" : "invalid" };
  }
}
