import { defineConfig, devices } from "@playwright/test";

const frontendPort = Number(process.env.WARDN_E2E_FRONTEND_PORT ?? 3100);
const mockBackendPort = Number(process.env.WARDN_E2E_BACKEND_PORT ?? 4100);
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const mockBackendUrl = `http://127.0.0.1:${mockBackendPort}`;
const sessionCookieName = process.env.WARDN_E2E_SESSION_COOKIE_NAME ?? "wardn_e2e_session";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
    },
  },
  webServer: [
    {
      command: `WARDN_E2E_BACKEND_PORT=${mockBackendPort} WARDN_SESSION_COOKIE_NAME=${sessionCookieName} node e2e/mock-backend.mjs`,
      url: `${mockBackendUrl}/__test/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `HOSTNAME=127.0.0.1 PORT=${frontendPort} WARDN_BACKEND_URL=${mockBackendUrl} WARDN_SESSION_COOKIE_NAME=${sessionCookieName} node .next/standalone/wardn/frontend/server.js`,
      url: `${frontendUrl}/login`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } },
    },
  ],
});
