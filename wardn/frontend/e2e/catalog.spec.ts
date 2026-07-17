import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from "@playwright/test";

const mockBackendUrl = `http://127.0.0.1:${process.env.WARDN_E2E_BACKEND_PORT ?? 4100}`;
const organizationId = "org-1";
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

async function resetBackend(
  request: APIRequestContext,
  sources?: unknown[],
  overrides: Record<string, unknown> = {}
) {
  await request.post(`${mockBackendUrl}/__test/reset`, {
    data: { ...overrides, ...(sources === undefined ? {} : { sources }) },
  });
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

async function openAuthenticated(page: Page, path: string, baseURL: string) {
  await authenticate(page.context(), baseURL);
  await page.goto(path);
}

test.describe("catalog source management", () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test("creates a Wardn Hub source from only the Hub URL and token", async ({
    baseURL,
    page,
    request,
  }) => {
    await resetBackend(request, []);
    await openAuthenticated(page, `/org/${organizationId}/catalog/new`, baseURL ?? "");

    await expect(page.getByRole("heading", { name: "New source" })).toBeVisible();
    await expect(page.getByLabel("Hub URL")).toHaveValue("https://hub.wardnai.dev");
    await expect(page.getByLabel("Secret backend")).toContainText("k3s wardn");

    await page.getByLabel("Name").fill("Production Hub");
    await page.getByLabel("API token").fill("hub-token");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page).toHaveURL(new RegExp(`/org/${organizationId}/catalog$`));
    const productionHubRow = page.getByRole("row").filter({ hasText: "Production Hub" });
    await expect(productionHubRow).toBeVisible();
    await expect(productionHubRow).toContainText("https://hub.wardnai.dev");
    await expect(productionHubRow).not.toContainText("Token stored");

    const createRequest = (await backendRequests(request)).find(
      (entry) =>
        entry.method === "POST" &&
        entry.path === `/api/v1/organizations/${organizationId}/mcp/catalog/sources`
    );
    expect(createRequest?.body).toMatchObject({
      provider: "wardn_hub",
      baseUrl: "https://hub.wardnai.dev",
      apiToken: "hub-token",
      apiTokenSecretStoreId: "store-1",
    });
  });

  test("keeps the existing token when editing a source without entering a token", async ({
    baseURL,
    page,
    request,
  }) => {
    await openAuthenticated(page, `/org/${organizationId}/catalog/edit/source-1`, baseURL ?? "");

    await expect(page.getByRole("heading", { name: "Edit source" })).toBeVisible();
    await expect(page.getByLabel("Hub URL")).toHaveValue("https://hub.wardnai.dev");
    await expect(page.getByLabel("API token")).toHaveAttribute(
      "placeholder",
      "Leave blank to keep current token"
    );

    await page.getByLabel("Name").fill("Wardn Hub Production");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page).toHaveURL(new RegExp(`/org/${organizationId}/catalog$`));
    await expect(
      page.getByRole("cell", { exact: true, name: "Wardn Hub Production" })
    ).toBeVisible();

    const patchRequest = (await backendRequests(request)).find(
      (entry) =>
        entry.method === "PATCH" &&
        entry.path === `/api/v1/organizations/${organizationId}/mcp/catalog/sources/source-1`
    );
    expect(patchRequest?.body).toMatchObject({
      name: "Wardn Hub Production",
      provider: "wardn_hub",
      baseUrl: "https://hub.wardnai.dev",
    });
    expect(patchRequest?.body).not.toHaveProperty("apiToken");
  });

  test("polls, syncs, and deletes a catalog source from the list", async ({
    baseURL,
    page,
    request,
  }) => {
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");

    const wardnHubRow = page.getByRole("row").filter({ hasText: "Wardn Hub" });
    await expect(wardnHubRow).toBeVisible();
    await page.getByRole("button", { name: "Sync Wardn Hub" }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "Synced 2 server definitions." })
    ).toBeVisible();
    await expect(page.getByRole("cell", { name: /Jun 30/ })).toBeVisible();
    const jobRequests = (await backendRequests(request)).filter((entry) =>
      entry.path.includes("/mcp/catalog/jobs/")
    );
    expect(jobRequests).toHaveLength(2);

    await page.getByRole("button", { name: "Delete Wardn Hub" }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "Catalog source deleted." })
    ).toBeVisible();
    await expect(page.getByText("No catalog sources")).toBeVisible();
  });

  test("stops polling a catalog job after navigation", async ({ baseURL, page, request }) => {
    await resetBackend(request, undefined, { catalogJobPollsBeforeSuccess: 100 });
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");

    await page.getByRole("button", { name: "Sync Wardn Hub" }).click();
    await expect(page.getByRole("button", { name: "Edit Wardn Hub" })).toBeDisabled();
    await expect(page.getByRole("link", { name: "Edit Wardn Hub" })).toHaveCount(0);
    await expect
      .poll(async () =>
        (await backendRequests(request)).filter((entry) =>
          entry.path.includes("/mcp/catalog/jobs/")
        ).length
      )
      .toBeGreaterThan(0);

    await page.goto("/org");
    const requestsAfterNavigation = (await backendRequests(request)).filter((entry) =>
      entry.path.includes("/mcp/catalog/jobs/")
    ).length;
    await page.waitForTimeout(2_000);
    const requestsAfterWaiting = (await backendRequests(request)).filter((entry) =>
      entry.path.includes("/mcp/catalog/jobs/")
    ).length;
    expect(requestsAfterWaiting).toBe(requestsAfterNavigation);
  });

  test("loads workspaces only for the organization selected by the route", async ({
    baseURL,
    page,
    request,
  }) => {
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");
    await expect(page.getByRole("heading", { name: "Catalog" })).toBeVisible();

    const workspaceRequests = (await backendRequests(request)).filter((entry) =>
      entry.path.endsWith("/workspaces")
    );
    expect(workspaceRequests).toEqual([
      expect.objectContaining({
        method: "GET",
        path: `/api/v1/organizations/${organizationId}/workspaces`,
      }),
    ]);
  });

  test("displays the first workspace's actual name", async ({ baseURL, page }) => {
    await openAuthenticated(page, `/org/${organizationId}/workspaces`, baseURL ?? "");

    const workspaceButton = page.getByRole("button", { name: "Open Platform" });
    await expect(workspaceButton.getByRole("heading", { name: "Platform" })).toBeVisible();
    await expect(page.getByText("Default Workspace", { exact: true })).toHaveCount(0);
  });

  test("smoke: redirects protected catalog pages to login without a session", async ({ page }) => {
    await page.goto(`/org/${organizationId}/catalog`);

    await expect(page).toHaveURL(/\/login\?next=/);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("redirects an expired backend session to reauthentication", async ({
    baseURL,
    page,
    request,
  }) => {
    await resetBackend(request, undefined, { organizationsStatus: 401 });
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");

    await expect(page).toHaveURL(/\/login\?reauth=1&next=/);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("reauthenticates browser API operations after session expiry", async ({
    baseURL,
    page,
    request,
  }) => {
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");
    await expect(page.getByRole("row").filter({ hasText: "Wardn Hub" })).toBeVisible();
    await resetBackend(request, undefined, { catalogStatus: 401 });

    await page.getByRole("button", { name: "Sync Wardn Hub" }).click();

    await expect(page).toHaveURL(/\/login\?reauth=1&next=/);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("announces catalog operation failures", async ({ baseURL, page, request }) => {
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");
    await expect(page.getByRole("row").filter({ hasText: "Wardn Hub" })).toBeVisible();
    await resetBackend(request, undefined, { catalogStatus: 500 });

    await page.getByRole("button", { name: "Sync Wardn Hub" }).click();

    await expect(
      page.getByRole("alert").filter({ hasText: "catalog request failed" })
    ).toBeVisible();
  });

  test("shows retryable API failures instead of an empty catalog", async ({
    baseURL,
    page,
    request,
  }) => {
    await resetBackend(request, undefined, { catalogStatus: 503 });
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");

    await expect(page.getByRole("heading", { name: "This page could not be loaded" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(page.getByText("No catalog sources")).not.toBeVisible();
  });

  test("preserves forbidden and not-found backend responses", async ({
    baseURL,
    page,
    request,
  }) => {
    await resetBackend(request, undefined, { catalogStatus: 403 });
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");
    await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible();

    await resetBackend(request, undefined, { catalogStatus: 404 });
    await page.goto(`/org/${organizationId}/catalog`);
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });

  test("reveals a new API token without writing it to browser storage", async ({
    baseURL,
    page,
  }) => {
    await openAuthenticated(page, `/org/${organizationId}/tokens/new`, baseURL ?? "");
    await expect(page.getByText("Create Gateway Token", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Create token" }).click();

    await expect(page.getByText("Token created", { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Token" })).toHaveValue(
      "wardn_test_secret_token"
    );
    expect(
      await page.evaluate(() => ({
        local: Object.keys(localStorage),
        session: Object.keys(sessionStorage),
      }))
    ).toEqual({ local: [], session: [] });

    await page.reload();
    await expect(page.getByText("Create Gateway Token", { exact: true })).toBeVisible();
    await expect(page.getByText("wardn_test_secret_token")).not.toBeVisible();
  });

  test("serves browser security headers", async ({ request }) => {
    const response = await request.get("/login");
    expect(response.ok()).toBeTruthy();
    expect(response.headers()["content-security-policy"]).toContain("default-src 'self'");
    expect(response.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(response.headers()["x-frame-options"]).toBe("DENY");
    expect(response.headers()["x-content-type-options"]).toBe("nosniff");
    expect(response.headers()["referrer-policy"]).toBe("no-referrer");
    expect(response.headers()["permissions-policy"]).toContain("camera=()");
  });
});

test.describe("catalog source visual coverage", () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test("new Wardn Hub source page matches desktop snapshot", async ({ baseURL, page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await openAuthenticated(page, `/org/${organizationId}/catalog/new`, baseURL ?? "");
    await expect(page.getByRole("heading", { name: "New source" })).toBeVisible();

    await expect(page).toHaveScreenshot("catalog-new-source-desktop.png", {
      fullPage: true,
    });
  });

  test("new Wardn Hub source page remains usable on mobile", async ({ baseURL, page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openAuthenticated(page, `/org/${organizationId}/catalog/new`, baseURL ?? "");
    await expect(page.getByLabel("Hub URL")).toBeVisible();
    await expect(page.getByLabel("API token")).toBeVisible();

    await expect(page).toHaveScreenshot("catalog-new-source-mobile.png", {
      fullPage: true,
    });
  });
});
