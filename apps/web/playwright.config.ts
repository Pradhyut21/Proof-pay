import { defineConfig } from "@playwright/test";

/**
 * Judge-flow e2e. Starts the real Rust API (on the committed data/demo fixture) and the built Next.js app.
 * Browser: PP_E2E_CHANNEL (default "msedge" so no browser download is needed on Windows; use "chrome" or
 * unset+`npx playwright install chromium` elsewhere).
 */
const channel = process.env.PP_E2E_CHANNEL ?? "msedge";
const apiBin = process.platform === "win32" ? "target/debug/pp-api.exe" : "target/debug/pp-api";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:3000", channel, trace: "retain-on-failure" },
  webServer: [
    {
      command: apiBin,
      cwd: "../..",
      url: "http://127.0.0.1:8787/health",
      reuseExistingServer: true,
      timeout: 60_000,
      env: {
        PP_DATA_DIR: "data/demo",
        PP_RUNS_DIR: "data/runs_e2e",
        PP_REVEAL_TOKEN: "local-dev",
        PP_REPO_ROOT: ".",
        PP_MAX_GENERATE_COUNT: "4",
      },
    },
    {
      command: "pnpm start",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
