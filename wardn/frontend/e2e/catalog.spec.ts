import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from "@playwright/test";

const mockBackendUrl = `http://127.0.0.1:${process.env.WARDN_E2E_BACKEND_PORT ?? 4100}`;
const organizationId = "org-1";

async function authenticate(context: BrowserContext, baseURL: string) {
  await context.addCookies([
    {
      name: "wardn_session",
      value: "test-session",
      url: baseURL,
    },
  ]);
}

async function resetBackend(request: APIRequestContext, sources?: unknown[]) {
  await request.post(`${mockBackendUrl}/__test/reset`, {
    data: sources === undefined ? {} : { sources },
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
    await expect(page.getByRole("cell", { name: "Wardn Hub Production" })).toBeVisible();

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

  test("syncs and deletes a catalog source from the list", async ({ baseURL, page }) => {
    await openAuthenticated(page, `/org/${organizationId}/catalog`, baseURL ?? "");

    const wardnHubRow = page.getByRole("row").filter({ hasText: "Wardn Hub" });
    await expect(wardnHubRow).toBeVisible();
    await page.getByTitle("Sync").click();
    await expect(page.getByText("Synced 2 server definitions.")).toBeVisible();
    await expect(page.getByRole("cell", { name: /Jun 30/ })).toBeVisible();

    await page.getByTitle("Delete").click();
    await expect(page.getByText("Catalog source deleted.")).toBeVisible();
    await expect(page.getByText("No catalog sources")).toBeVisible();
  });

  test("smoke: redirects protected catalog pages to login without a session", async ({ page }) => {
    await page.goto(`/org/${organizationId}/catalog`);

    await expect(page).toHaveURL(/\/login\?next=/);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
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
