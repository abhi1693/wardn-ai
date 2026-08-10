import { defineConfig } from "cypress";

const frontendPort = Number(process.env.WARDN_CYPRESS_FRONTEND_PORT ?? 3200);
const mockBackendPort = Number(process.env.WARDN_CYPRESS_BACKEND_PORT ?? 4200);

export default defineConfig({
  allowCypressEnv: false,
  responseTimeout: 60_000,
  screenshotsFolder: "cypress/screenshots",
  video: false,
  viewportHeight: 900,
  viewportWidth: 1440,
  component: {
    devServer: {
      framework: "next",
      bundler: "webpack",
    },
    indexHtmlFile: "cypress/support/component-index.html",
    specPattern: "cypress/component/**/*.cy.tsx",
    supportFile: "cypress/support/component.tsx",
  },
  e2e: {
    baseUrl: `http://127.0.0.1:${frontendPort}`,
    env: {
      mockBackendUrl: `http://127.0.0.1:${mockBackendPort}`,
      sessionCookieName: process.env.WARDN_CYPRESS_SESSION_COOKIE_NAME ?? "wardn_cypress_session",
    },
    specPattern: "cypress/e2e/**/*.cy.ts",
    supportFile: "cypress/support/e2e.ts",
  },
});
