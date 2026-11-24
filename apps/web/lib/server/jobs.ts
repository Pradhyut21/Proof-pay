import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { ID_RE, serverConfig } from "./config";

/**
 * INTERIM job runner (stands in for the generation/evaluation job routes that the Axum API issue still has
 * to add). Runs the Python factory with a fixed argument vector, writes a contract bundle, then (re)starts a
 * second Axum API process on that bundle so tasks are served, scored and revealed by the real service.
 */
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface JobRecord {
  job_id: string;
  status: JobStatus;
  error: string | null;
  task_ids: string[];
  reused: boolean;
  started_at: number;
}

const SEED_RE = /^[A-Za-z0-9_-]{1,40}$/;
const DIFFICULTIES = ["easy", "medium", "hard"] as const;
const MAX_STDERR = 400;

interface Holder {
  factoryChild?: ChildProcess;
  factoryDir?: string;
  inflight: Map<string, Promise<void>>;
}
const g = globalThis as unknown as { __ppJobs?: Holder };
const state: Holder = (g.__ppJobs ??= { inflight: new Map() });

export function currentFactoryDir(): string | undefined {
  return state.factoryDir;
}

export function validateJobInput(
  input: unknown,
): { seed: string; count: number; difficulty: string } | string {
  const o = (input ?? {}) as Record<string, unknown>;
  if (typeof o.seed !== "string" || !SEED_RE.test(o.seed))
    return "seed must be 1-40 characters of A-Z a-z 0-9 _ -";
  const count = o.count;
  if (
    typeof count !== "number" ||
    !Number.isInteger(count) ||
    count < 1 ||
    count > serverConfig.maxCount
  ) {
    return `count must be a whole number from 1 to ${serverConfig.maxCount}`;
  }
  if (
    typeof o.difficulty !== "string" ||
    !(DIFFICULTIES as readonly string[]).includes(o.difficulty)
  ) {
    return "difficulty must be easy, medium or hard";
  }
  return { seed: o.seed, count, difficulty: o.difficulty };
}

export const jobId = (seed: string, count: number, difficulty: string): string =>
  "j_" + createHash("sha256").update(`${seed}|${count}|${difficulty}`).digest("hex").slice(0, 16);

const jobDir = (id: string) => path.join(serverConfig.runsDir, id);
const statusFile = (id: string) => path.join(jobDir(id), "job.json");

function writeStatus(rec: JobRecord): void {
  fs.mkdirSync(jobDir(rec.job_id), { recursive: true });
  fs.writeFileSync(statusFile(rec.job_id), JSON.stringify(rec));
}

function taskIds(dir: string): string[] {
  const file = path.join(dir, "public", "tasks.jsonl");
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => (JSON.parse(l) as { task_id: string }).task_id);
}

export function getJob(id: string): JobRecord | null {
  if (!ID_RE.test(id)) return null;
  try {
    const rec = JSON.parse(fs.readFileSync(statusFile(id), "utf8")) as JobRecord;
    const live = state.inflight.has(id);
    if ((rec.status === "running" || rec.status === "queued") && !live) {
      // The process that owned this job is gone (server restart or crash): recover instead of hanging.
      const stale = {
        ...rec,
        status: "failed" as const,
        error: "job was interrupted; start it again",
      };
      writeStatus(stale);
      return stale;
    }
    return rec;
  } catch {
    return null;
  }
}

async function waitHealthy(base: string, ms: number): Promise<boolean> {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const r = await fetch(`${base}/healthz`, { signal: AbortSignal.timeout(1000) });
      if (r.ok) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

async function ensureFactoryApi(dir: string): Promise<void> {
  if (state.factoryDir === dir && state.factoryChild && state.factoryChild.exitCode === null)
    return;
  state.factoryChild?.kill();
  const url = new URL(serverConfig.factoryApi);
  const sqlite = path.join(dir, "api.sqlite");
  const address = `${url.hostname}:${url.port}`;
  // Windows without a native Rust toolchain can run the Linux API inside WSL (PP_API_WSL_DISTRO).
  const distro = process.env.PP_API_WSL_DISTRO;
  const toWsl = (p: string) =>
    p.replace(/^([A-Za-z]):/, (_m, d: string) => `/mnt/${d.toLowerCase()}`).replaceAll("\\", "/");
  if (distro) {
    // Killing wsl.exe does not stop the Linux process, so free the port explicitly.
    spawnSync("wsl.exe", ["-d", distro, "-e", "pkill", "-f", `panelproof-api .*${address}`], {
      stdio: "ignore",
    });
  }
  const [cmd, args]: [string, string[]] = distro
    ? [
        "wsl.exe",
        [
          "-d",
          distro,
          "-e",
          "env",
          `PANELPROOF_REVEAL_TOKEN=${serverConfig.revealToken}`,
          serverConfig.apiBin,
          toWsl(dir),
          toWsl(sqlite),
          address,
        ],
      ]
    : [serverConfig.apiBin, [dir, sqlite, address]];
  const child = spawn(cmd, args, {
    env: { ...process.env, PANELPROOF_REVEAL_TOKEN: serverConfig.revealToken },
    stdio: "ignore",
    windowsHide: true,
  });
  state.factoryChild = child;
  state.factoryDir = dir;
  if (!(await waitHealthy(serverConfig.factoryApi, 20_000)))
    throw new Error("the task API did not start");
}

function runFactory(id: string, seed: string, count: number, difficulty: string): Promise<void> {
  const dir = jobDir(id);
  return new Promise((resolve) => {
    const base: JobRecord = {
      job_id: id,
      status: "running",
      error: null,
      task_ids: [],
      reused: false,
      started_at: Date.now(),
    };
    writeStatus(base);
    const bundle = path.join(dir, "bundle");
    const child = spawn(
      serverConfig.python,
      [
        "-m",
        "panelproof.cli",
        "factory",
        "--seed",
        seed,
        "--count",
        String(count),
        "--out",
        bundle,
        "--difficulty",
        difficulty,
      ],
      {
        cwd: serverConfig.root,
        env: { ...process.env, PYTHONPATH: path.join(serverConfig.root, "python", "src") },
        stdio: ["ignore", "ignore", "pipe"],
        windowsHide: true,
      },
    );
    let err = "";
    child.stderr?.on("data", (d: Buffer) => {
      if (err.length < 4000) err += d.toString();
    });
    const timer = setTimeout(() => child.kill(), serverConfig.jobDeadlineMs);
    const fail = (message: string) => {
      writeStatus({ ...base, status: "failed", error: message });
      resolve();
    };
    child.on("error", () => {
      clearTimeout(timer);
      fail("could not start the generator");
    });
    child.on("close", async (code) => {
      clearTimeout(timer);
      if (code !== 0)
        return fail(
          code === null
            ? "generation timed out"
            : `generator failed: ${err.trim().split("\n").pop()?.slice(0, MAX_STDERR) ?? ""}`,
        );
      try {
        const ids = taskIds(bundle);
        await ensureFactoryApi(bundle);
        writeStatus({ ...base, status: "succeeded", task_ids: ids });
        resolve();
      } catch (e) {
        fail(e instanceof Error ? e.message : "task API failed");
      }
    });
  });
}

export async function startJob(
  seed: string,
  count: number,
  difficulty: string,
): Promise<JobRecord> {
  const id = jobId(seed, count, difficulty);
  const existing = getJob(id);
  if (state.inflight.has(id))
    return (
      existing ?? {
        job_id: id,
        status: "running",
        error: null,
        task_ids: [],
        reused: false,
        started_at: Date.now(),
      }
    );
  const bundle = path.join(jobDir(id), "bundle");
  if (existing?.status === "succeeded" && fs.existsSync(path.join(bundle, "manifest.json"))) {
    try {
      await ensureFactoryApi(bundle);
      return { ...existing, reused: true };
    } catch {
      /* fall through and regenerate */
    }
  }
  const p = runFactory(id, seed, count, difficulty).finally(() => state.inflight.delete(id));
  state.inflight.set(id, p);
  return {
    job_id: id,
    status: "running",
    error: null,
    task_ids: [],
    reused: false,
    started_at: Date.now(),
  };
}
