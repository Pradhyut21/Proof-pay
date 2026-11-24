import path from "node:path";

/** Server-only configuration. Nothing here is ever sent to the browser. */
const root = process.env.PP_REPO_ROOT ?? path.resolve(process.cwd(), "..", "..");

export const serverConfig = {
  root,
  demoApi: process.env.PP_API_DEMO ?? "http://127.0.0.1:3001",
  factoryApi: process.env.PP_API_FACTORY ?? "http://127.0.0.1:3002",
  /** Developer-supplied local token for the dev-only reveal/attempt routes (16-128 visible ASCII chars). */
  revealToken: process.env.PANELPROOF_REVEAL_TOKEN ?? "",
  demoDir: process.env.PP_DEMO_DIR ?? path.join(root, "data", "demo"),
  runsDir: process.env.PP_RUNS_DIR ?? path.join(root, "data", "runs"),
  python: process.env.PP_PYTHON ?? (process.platform === "win32" ? "python" : "python3"),
  apiBin:
    process.env.PP_API_BIN ??
    path.join(
      root,
      "target",
      "debug",
      process.platform === "win32" ? "panelproof-api.exe" : "panelproof-api",
    ),
  maxCount: Number(process.env.PP_MAX_GENERATE_COUNT ?? "4"),
  jobDeadlineMs: Number(process.env.PP_JOB_DEADLINE_SECS ?? "120") * 1000,
};

export const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
