import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

const mockBackendUrl = `http://127.0.0.1:${process.env.WARDN_E2E_BACKEND_PORT ?? 4100}`;
const organizationId = "org-1";
const workspaceId = "workspace-1";
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
      requests: Array<{
        method: string;
        path: string;
        query?: Record<string, string>;
        body?: Record<string, unknown>;
      }>;
    }
  ).requests;
}

test.describe("skill marketplace", () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test("discovers, approves, assigns, and shows usage evidence", async ({
    baseURL,
    page,
    request,
  }) => {
    await authenticate(page.context(), baseURL ?? "");
    await page.goto(`/org/${organizationId}/workspace/${workspaceId}/skills`);

    await expect(page.getByRole("heading", { level: 1, name: "Skill Marketplace" })).toBeVisible();
    await expect(page.getByText("Discover Hub Skills")).toBeVisible();

    const searchInput = page.getByLabel("Search Wardn Hub skills");
    await expect(searchInput).toHaveValue("");
    await searchInput.fill("kubernetes ops");
    const searchResponse = page.waitForResponse(
      (response) => response.url().includes("/skills/search") && response.status() === 200
    );
    await page.getByRole("button", { name: "Search" }).click();
    await searchResponse;
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();

    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByRole("button", { name: /Workspace Library/ })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await expect(page.getByText("hash-123")).toBeVisible();

    const assignmentResponse = page.waitForResponse(
      (response) => response.url().includes("/skills/library/library-1/agents")
        && response.status() === 200
    );
    await page.getByLabel("Workspace Assistant").click();
    await assignmentResponse;
    await expect(page.getByLabel("Workspace Assistant")).toBeChecked();
    await page.getByRole("button", { name: /Usage/ }).click();
    await expect(page.getByText("Fetched owner/repo/kubernetes-ops with audit pass.")).toBeVisible();
    await expect(page.getByText("Approved").last()).toBeVisible();

    const requests = await backendRequests(request);
    expect(
      requests.find(
        (entry) =>
          entry.method === "POST" &&
          entry.path ===
            `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/skills/library`
      )?.body
    ).toMatchObject({ skillId: "owner/repo/kubernetes-ops" });
    expect(
      requests.find(
        (entry) =>
          entry.method === "PATCH" &&
          entry.path ===
            `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/skills/library/library-1/agents`
      )?.body
    ).toMatchObject({ agentIds: ["agent-1"] });
  });
});
