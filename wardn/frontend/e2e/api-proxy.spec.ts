import { expect, test, type APIRequestContext } from "@playwright/test";

const mockBackendUrl = `http://127.0.0.1:${process.env.WARDN_E2E_BACKEND_PORT ?? 4100}`;
const organizationId = "org-1";
const workspaceId = "workspace-1";

async function resetBackend(request: APIRequestContext) {
  await request.post(`${mockBackendUrl}/__test/reset`, { data: {} });
}

async function backendRequests(request: APIRequestContext) {
  const response = await request.get(`${mockBackendUrl}/__test/requests`);
  expect(response.ok()).toBeTruthy();
  return (
    (await response.json()) as {
      requests: Array<{
        body?: Record<string, unknown>;
        method: string;
        path: string;
      }>;
    }
  ).requests;
}

test.describe("frontend API proxy", () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test("forwards agent approval decisions through same-origin /api/v1", async ({ request }) => {
    const approvalId = "11111111-1111-4111-8111-111111111111";
    const response = await request.post(
      `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/agents/agent-1/tool-approvals/${approvalId}`,
      { data: { decision: "deny" } }
    );

    expect(response.ok()).toBeTruthy();
    expect(await response.json()).toMatchObject({
      approvalId,
      error: "Denied by user.",
      status: "denied",
      toolName: "namespace_list",
    });

    const approvalRequest = (await backendRequests(request)).find(
      (entry) =>
        entry.method === "POST" &&
        entry.path ===
          `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/agents/agent-1/tool-approvals/${approvalId}`
    );
    expect(approvalRequest?.body).toMatchObject({ decision: "deny" });
  });
});
