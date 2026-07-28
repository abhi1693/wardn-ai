import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

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

async function resetBackend(request: APIRequestContext) {
  await request.post(`${mockBackendUrl}/__test/reset`, { data: {} });
}

async function backendRequests(request: APIRequestContext) {
  const response = await request.get(`${mockBackendUrl}/__test/requests`);
  expect(response.ok()).toBeTruthy();
  return (
    (await response.json()) as {
      requests: Array<{ method: string; path: string }>;
    }
  ).requests;
}

test.describe("usage summary scope", () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test("combines organization and personal usage under a scope filter", async ({
    baseURL,
    page,
    request,
  }) => {
    await authenticate(page.context(), baseURL ?? "");
    await page.goto(`/org/${organizationId}/usage`);

    await expect(page.getByRole("heading", { name: "Usage" })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "My Usage" })
    ).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Organization" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(
      page.getByText("Organization usage by user, workspace, agent, and model")
    ).toBeVisible();
    await expect(page.getByText("By user", { exact: true })).toBeVisible();

    await page.getByRole("tab", { name: "My usage" }).click();

    await expect(page).toHaveURL(new RegExp(`/org/${organizationId}/usage\\?scope=me$`));
    await expect(page.getByRole("tab", { name: "My usage" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(
      page.getByText("Your attributed model requests, tokens, cost, and tool calls")
    ).toBeVisible();
    await expect(page.getByText("My models", { exact: true })).toBeVisible();

    const usageRequests = (await backendRequests(request)).filter((entry) =>
      entry.path.includes("/usage")
    );
    expect(usageRequests.map((entry) => entry.path)).toEqual([
      `/api/v1/organizations/${organizationId}/usage/summary`,
      "/api/v1/me/usage",
    ]);
  });

  test("redirects the old personal usage route to the usage filter", async ({ baseURL, page }) => {
    await authenticate(page.context(), baseURL ?? "");
    await page.goto(`/org/${organizationId}/usage/me`);

    await expect(page).toHaveURL(new RegExp(`/org/${organizationId}/usage\\?scope=me$`));
    await expect(page.getByRole("heading", { name: "Usage" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "My usage" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });
});
