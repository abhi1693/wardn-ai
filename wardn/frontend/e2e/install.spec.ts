import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

const mockBackendUrl = `http://127.0.0.1:${process.env.WARDN_E2E_BACKEND_PORT ?? 4100}`;
const organizationId = "org-1";
const workspaceId = "workspace-1";
const serverName = "io.github.acamolese/google-search-console-mcp";
const sessionCookieName = process.env.WARDN_E2E_SESSION_COOKIE_NAME ?? "wardn_e2e_session";

async function authenticate(context: BrowserContext, baseURL: string) {
  await context.addCookies([
    {
      name: sessionCookieName,
      value: "test-session",
      url: baseURL,
    },
  ]);
}

async function resetBackend(request: APIRequestContext) {
  await request.post(`${mockBackendUrl}/__test/reset`, { data: {} });
}

async function backendRequests(request: APIRequestContext) {
  const response = await request.get(`${mockBackendUrl}/__test/requests`);
  expect(response.ok()).toBeTruthy();
  return (
    (await response.json()) as {
      requests: Array<{ method: string; path: string; body?: Record<string, unknown> }>;
    }
  ).requests;
}

test.describe("MCP install runtime selection", () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test("shows the selected package version and submits the switched runtime", async ({
    baseURL,
    page,
    request,
  }) => {
    await authenticate(page.context(), baseURL ?? "");
    await page.goto(
      `/org/${organizationId}/workspace/${workspaceId}/install/new?serverName=${encodeURIComponent(
        serverName
      )}&version=1.0.0`
    );

    await expect(page.getByRole("heading", { name: "Add MCP server" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Runtime" })).toContainText("NPM");

    const selectedPackage = page.getByTestId("install-target-details");
    await expect(selectedPackage).toContainText("@acamolese/google-search-console-mcp");
    await expect(selectedPackage).toContainText("Package version: 1.0.0");

    await page.getByRole("combobox", { name: "Runtime" }).click();
    await page.getByRole("option", { name: /UVX .* google-search-console-mcp/ }).click();

    await expect(page.getByRole("combobox", { name: "Runtime" })).toContainText("UVX");
    await expect(selectedPackage).toContainText("google-search-console-mcp");
    await expect(selectedPackage).toContainText("Package version: 1.0.0");

    await page.getByRole("button", { exact: true, name: "Add" }).click();

    await expect(page).toHaveURL(
      new RegExp(`/org/${organizationId}/workspace/${workspaceId}/install$`)
    );
    const installRequest = (await backendRequests(request)).find(
      (entry) =>
        entry.method === "PUT" &&
        entry.path ===
          `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/mcp/registry/installed-servers/${serverName}`
    );
    expect(installRequest?.body).toMatchObject({
      version: "1.0.0",
      configName: "default",
      installTarget: "package:1",
    });
  });
});
