import { defineConfig } from "@playwright/test";

/**
 * Judge-flow e2e. Starts the real Axum API on the committed data/demo bundle and the built Next.js app, which
 * proxies to it and starts a second API for freshly generated bundles.
 *
 * Browser: PP_E2E_CHANNEL (default "msedge" so no browser download is needed on Windows; use "chrome" or
 * run `pnpm exec playwright install chromium` and set PP_E2E_CHANNEL= to use the bundled Chromium).
 * If you already started the servers (for example the API inside WSL), they are reused.
 */
const channel = process.env.PP_E2E_CHANNEL || undefined;
const token = process.env.PANELPROOF_REVEAL_TOKEN ?? "local-dev-token-0123";
const apiBin =
  process.env.PP_API_BIN ??
  (process.platform === "win32"
    ? "target/debug/panelproof-api.exe"
    : "target/debug/panelproof-api");

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    channel: channel ?? "msedge",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${apiBin} data/demo data/runs/e2e-demo.sqlite 127.0.0.1:3001`,
      cwd: "../..",
      url: "http://127.0.0.1:3001/healthz",
      reuseExistingServer: true,
      timeout: 60_000,
      env: { PANELPROOF_REVEAL_TOKEN: token },
    },
    {
      command: "pnpm start",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: true,
      timeout: 60_000,
      env: { PANELPROOF_REVEAL_TOKEN: token },
    },
  ],
});
