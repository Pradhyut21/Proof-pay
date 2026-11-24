import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { createConnection } from "node:net";
import path from "node:path";
import type { Job } from "../types";
import { ID_RE, serverConfig } from "./config";

type JobRecord = Job & { started_at: number };

/** The local shim serializes generation and serves one imported factory bundle at a time. */
const SEED_RE = /^[A-Za-z0-9_-]{1,40}$/;
const DIFFICULTIES = ["easy", "medium", "hard"] as const;
const NOT_AVAILABLE = "This factory result is no longer active. Generate it again to reopen it.";

interface Child {
  process: ChildProcess;
  closed: Promise<number | null>;
  running: () => boolean;
}

interface FactoryApi {
  id: string;
  dir: string;
  child: Child;
  stop: () => void;
  ready: boolean;
}

interface Holder {
  factory?: FactoryApi;
  activeId?: string;
}

const globals = globalThis as typeof globalThis & { __ppFactoryLifecycle?: Holder };
const state = (globals.__ppFactoryLifecycle ??= {});

function activeFactory(id: string): FactoryApi | undefined {
  const factory = state.factory;
  return factory?.id === id && factory.ready && factory.child.running() ? factory : undefined;
}

export function currentFactoryDir(id: string): string | undefined {
  return activeFactory(id)?.dir;
}

export function validateJobInput(
  input: unknown,
): { seed: string; count: number; difficulty: string } | string {
  const o = (input ?? {}) as Record<string, unknown>;
  if (typeof o.seed !== "string" || !SEED_RE.test(o.seed))
    return "Seed must be 1–40 characters of A-Z, a-z, 0-9, _ or -.";
  const count = o.count;
  if (
    typeof count !== "number" ||
    !Number.isSafeInteger(count) ||
    count < 1 ||
    count > (Number.isSafeInteger(serverConfig.maxCount) ? serverConfig.maxCount : 4)
  )
    return "Count is outside the configured panel limit.";
  if (
    typeof o.difficulty !== "string" ||
    !(DIFFICULTIES as readonly string[]).includes(o.difficulty)
  )
    return "Difficulty must be easy, medium or hard.";
  return { seed: o.seed, count, difficulty: o.difficulty };
}

export const jobId = (seed: string, count: number, difficulty: string): string =>
  "j_" + createHash("sha256").update(`${seed}|${count}|${difficulty}`).digest("hex").slice(0, 16);

const jobDir = (id: string) => path.join(serverConfig.runsDir, id);
const statusFile = (id: string) => path.join(jobDir(id), "job.json");

function writeStatus(job: JobRecord): void {
  fs.mkdirSync(jobDir(job.job_id), { recursive: true });
  const file = statusFile(job.job_id);
  fs.writeFileSync(file + ".tmp", JSON.stringify(job));
  fs.renameSync(file + ".tmp", file);
}

function readStatus(id: string): JobRecord | null {
  if (!ID_RE.test(id)) return null;
  try {
    return JSON.parse(fs.readFileSync(statusFile(id), "utf8")) as JobRecord;
  } catch {
    return null;
  }
}

export function getJob(id: string): JobRecord | null {
  const job = readStatus(id);
  if (job?.status === "succeeded" && !activeFactory(id)) {
    return { ...job, status: "expired", task_ids: [], error: NOT_AVAILABLE };
  }
  if ((job?.status === "running" || job?.status === "queued") && state.activeId !== id) {
    const interrupted = { ...job, status: "failed" as const, error: "The job was interrupted." };
    writeStatus(interrupted);
    return interrupted;
  }
  return job;
}

function taskIds(dir: string): [string, ...string[]] {
  const file = path.join(dir, "public", "tasks.jsonl");
  const ids = fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => (JSON.parse(line) as { task_id: string }).task_id);
  const [first, ...remaining] = ids;
  if (!first || ids.some((id) => typeof id !== "string" || !ID_RE.test(id))) {
    throw new Error("The generator returned no usable task IDs.");
  }
  return [first, ...remaining];
}

function manage(process: ChildProcess): Child {
  let stopped = false;
  const closed = new Promise<number | null>((resolve) => {
    process.on("error", () => {
      stopped = true;
    });
    process.once("close", (code) => {
      stopped = true;
      resolve(code);
    });
  });
  return {
    process,
    closed,
    running: () => !stopped && process.exitCode === null && process.signalCode === null,
  };
}

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function waitForClose(child: Child, timeout: number): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      child.closed.then(() => true),
      new Promise<false>((resolve) => {
        timer = setTimeout(() => resolve(false), timeout);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function stopFactory(factory: FactoryApi): Promise<void> {
  factory.ready = false;
  factory.stop();
  if (!(await waitForClose(factory.child, 5_000))) {
    factory.child.process.kill("SIGKILL");
    if (!(await waitForClose(factory.child, 2_000))) {
      throw new Error("The previous task API could not be stopped.");
    }
  }
  if (state.factory === factory) state.factory = undefined;
}

/** Distinguish a new child binding the port from a process already serving there. */
function assertPortFree(url: URL): Promise<void> {
  return new Promise((resolve, reject) => {
    const host = url.hostname.replace(/^\[|\]$/g, "");
    const socket = createConnection({ host, port: Number(url.port) });
    socket.setTimeout(1_000);
    socket.once("connect", () => {
      socket.destroy();
      reject(new Error("The factory API port is already in use."));
    });
    socket.once("timeout", () => {
      socket.destroy();
      reject(new Error("The factory API port did not respond."));
    });
    socket.once("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ECONNREFUSED") resolve();
      else reject(new Error("The factory API port could not be checked."));
    });
  });
}

const toWsl = (value: string) =>
  value
    .replace(/^([A-Za-z]):/, (_match, drive: string) => `/mnt/${drive.toLowerCase()}`)
    .replaceAll("\\", "/");

// WSL forwards stdin to this helper. Closing it stops precisely the Axum child this helper owns.
const WSL_WRAPPER = `exec 3<&0
"$@" </dev/null &
api_pid=$!
( IFS= read -r _ <&3; kill "$api_pid" 2>/dev/null || : ) &
watcher_pid=$!
status=0
wait "$api_pid" || status=$?
kill "$watcher_pid" 2>/dev/null || :
wait "$watcher_pid" 2>/dev/null || :
exit "$status"`;

function spawnFactory(id: string, dir: string, address: string): FactoryApi {
  const sqlite = path.join(dir, "api.sqlite");
  const distro = process.env.PP_API_WSL_DISTRO;
  const env = { ...process.env };
  if (serverConfig.revealToken) env.PANELPROOF_REVEAL_TOKEN = serverConfig.revealToken;
  else delete env.PANELPROOF_REVEAL_TOKEN;
  const processEnv = distro
    ? {
        ...env,
        WSLENV: [env.WSLENV, "PANELPROOF_REVEAL_TOKEN/u"].filter(Boolean).join(":"),
      }
    : env;
  const args = distro
    ? [
        "-d",
        distro,
        "-e",
        "sh",
        "-c",
        WSL_WRAPPER,
        "panelproof-factory",
        serverConfig.apiBin,
        toWsl(dir),
        toWsl(sqlite),
        address,
      ]
    : [dir, sqlite, address];
  const child = manage(
    spawn(distro ? "wsl.exe" : serverConfig.apiBin, args, {
      env: processEnv,
      stdio: [distro ? "pipe" : "ignore", "ignore", "ignore"],
      windowsHide: true,
    }),
  );
  // The wrapper may exit on its own before the parent closes the control pipe.
  child.process.stdin?.on("error", () => {});
  return {
    id,
    dir,
    child,
    ready: false,
    stop: () => {
      if (distro) child.process.stdin?.end();
      else if (child.running()) child.process.kill();
    },
  };
}

async function startFactoryApi(id: string, dir: string, firstTask: string): Promise<void> {
  if (state.factory) await stopFactory(state.factory);
  const url = new URL(serverConfig.factoryApi);
  if (url.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(url.hostname) || !url.port) {
    throw new Error("The factory API must use an explicit loopback address and port.");
  }
  await assertPortFree(url);
  const factory = spawnFactory(id, dir, `${url.hostname}:${url.port}`);
  state.factory = factory;
  const deadline = Date.now() + 20_000;
  while (factory.child.running() && Date.now() < deadline) {
    try {
      const response = await fetch(new URL(`/api/v1/tasks/${firstTask}`, url), {
        cache: "no-store",
        signal: AbortSignal.timeout(750),
      });
      if (response.ok && (await response.json()).task_id === firstTask && factory.child.running()) {
        factory.ready = true;
        return;
      }
    } catch {
      // Axum may still be validating the bundle and opening SQLite.
    }
    await delay(200);
  }
  await stopFactory(factory);
  throw new Error("The task API did not start with the generated bundle.");
}

async function generateBundle(
  dir: string,
  seed: string,
  count: number,
  difficulty: string,
): Promise<void> {
  const child = manage(
    spawn(
      serverConfig.python,
      [
        "-m",
        "panelproof.cli",
        "factory",
        `--seed=${seed}`,
        "--count",
        String(count),
        "--out",
        dir,
        "--difficulty",
        difficulty,
      ],
      {
        cwd: serverConfig.root,
        env: { ...process.env, PYTHONPATH: path.join(serverConfig.root, "python", "src") },
        stdio: "ignore",
        windowsHide: true,
      },
    ),
  );
  if (!(await waitForClose(child, serverConfig.jobDeadlineMs))) {
    child.process.kill("SIGKILL");
    if (!(await waitForClose(child, 2_000))) {
      throw new Error("Generation timed out and the worker did not shut down.");
    }
    throw new Error("Generation timed out.");
  }
  if ((await child.closed) !== 0)
    throw new Error("The generator could not produce a valid bundle.");
}

async function publishBundle(bundle: string, seed: string, count: number, difficulty: string) {
  const staging = fs.mkdtempSync(path.join(path.dirname(bundle), "build-"));
  const pending = path.join(staging, "bundle");
  await generateBundle(pending, seed, count, difficulty);
  taskIds(pending);
  const previous = path.join(staging, "previous");
  if (fs.existsSync(bundle)) fs.renameSync(bundle, previous);
  try {
    fs.renameSync(pending, bundle);
  } catch (error) {
    if (fs.existsSync(previous)) fs.renameSync(previous, bundle);
    throw error;
  }
  if (!fs.existsSync(previous)) fs.rmdirSync(staging);
}

export class FactoryBusy extends Error {}

export function startJob(seed: string, count: number, difficulty: string): JobRecord {
  const id = jobId(seed, count, difficulty);
  if (state.activeId) {
    if (state.activeId === id) {
      const current = readStatus(id);
      if (current) return current;
    }
    throw new FactoryBusy("Another factory job is running. Try again when it finishes.");
  }
  const existing = readStatus(id);
  if (existing?.status === "succeeded" && activeFactory(id)) {
    const reopened = { ...existing, reused: true };
    writeStatus(reopened);
    return reopened;
  }
  const bundle = path.join(jobDir(id), "bundle");
  const reused =
    existing?.status === "succeeded" && fs.existsSync(path.join(bundle, "manifest.json"));
  const job: JobRecord = {
    job_id: id,
    status: "running",
    error: null,
    task_ids: [],
    reused,
    started_at: Date.now(),
  };
  writeStatus(job);
  state.activeId = id;
  void (async () => {
    try {
      if (!reused) await publishBundle(bundle, seed, count, difficulty);
      const ids = taskIds(bundle);
      await startFactoryApi(id, bundle, ids[0]);
      writeStatus({ ...job, status: "succeeded", task_ids: ids });
    } catch (error) {
      writeStatus({
        ...job,
        status: "failed",
        error: error instanceof Error ? error.message : "The factory job failed.",
      });
    } finally {
      state.activeId = undefined;
    }
  })().catch(() => {
    // A status-file failure cannot be reported through that same file.
    console.error("Could not persist the factory job status.");
  });
  return job;
}
