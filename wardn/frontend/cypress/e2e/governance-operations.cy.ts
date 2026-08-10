const organizationId = "org-1";
const workspaceId = "workspace-1";
const workspaceBasePath = `/org/${organizationId}/workspace/${workspaceId}`;
const now = "2026-06-30T00:00:00.000Z";

const llmCredential = {
  apiKeySecretHandleId: "secret-credential-1",
  authMethod: "api_key",
  baseUrl: "https://api.openai.com/v1",
  createdAt: now,
  extraHeaders: {},
  id: "credential-1",
  isActive: true,
  name: "Operations OpenAI",
  oauthMetadata: {},
  oauthProvider: "",
  oauthScopes: [],
  organizationId,
  provider: "openai",
  status: "active",
  updatedAt: now,
  userId: null,
  visibility: "organization",
  workspaceId: null,
};

describe("governance and runtime operations", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
    cy.viewport(1280, 720);
  });

  it("changes the workspace guardrail default through the API", () => {
    cy.visit(`${workspaceBasePath}/guardrails`);
    cy.findByRole("heading", { level: 1, name: "Access Rules" }).should("be.visible");
    cy.findByText("Open by default").should("be.visible");
    cy.findByRole("button", { name: "Enable default deny" }).click();
    cy.findByText("Default deny").should("be.visible");
    cy.backendRequests().then((requests) => {
      const update = requests.find(
        (request) => request.method === "PATCH" && request.path.endsWith("/guardrails/settings")
      );
      expect(update?.body).to.deep.equal({ defaultDeny: true });
    });
  });

  it("checks health, inspects events, and stops a runtime session", () => {
    cy.visit(`${workspaceBasePath}/runtime`);
    cy.findByRole("heading", { level: 1, name: "Runtime Sessions" }).should("be.visible");
    cy.findByText("Google Search Console").should("be.visible");

    cy.findByRole("button", { name: "Show events for Google Search Console" }).click();
    cy.findByText("Tool call completed.").should("be.visible");
    cy.findByRole("button", { name: "Check health for Google Search Console" }).click();
    cy.findByText("Runtime process is ready.").should("be.visible");

    cy.findByRole("button", { name: "Stop runtime session for Google Search Console" }).click();
    cy.findByRole("status").should("contain.text", "Runtime session stopped.");
    cy.findByText("stopped").should("be.visible");
  });

  it("deletes an LLM credential through a destructive confirmation", () => {
    cy.resetBackend({ llmCredentials: [llmCredential] });
    cy.visit(`/org/${organizationId}/llm-credentials`);
    cy.findByRole("heading", { level: 1, name: "LLM Credentials" }).should("be.visible");
    cy.findByText("Operations OpenAI").should("be.visible");
    cy.findByRole("button", { name: "Delete Operations OpenAI" }).click();
    cy.findByRole("alertdialog", { name: "Delete Operations OpenAI?" }).should("be.visible");
    cy.findByRole("button", { name: "Delete credential" }).click();
    cy.findByText("No LLM credentials").should("be.visible");
    cy.backendRequests().then((requests) => {
      expect(
        requests.some(
          (request) =>
            request.method === "DELETE" && request.path.endsWith("/provider-credentials/credential-1")
        )
      ).to.equal(true);
    });
  });

  it("approves one exact stored tool call and renders its result", () => {
    cy.visit(`${workspaceBasePath}/agents/agent-1/approvals/approval-1`);
    cy.findByRole("heading", { level: 1, name: "Tool Approval" }).should("be.visible");
    cy.findByText("Needs approval").should("be.visible");
    cy.findByRole("button", { name: "Approve" }).click();
    cy.findByRole("status").should("contain.text", "Tool call approved and completed.");
    cy.findByText("namespace/default").should("be.visible");
    cy.findByRole("button", { name: "Approve" }).should("not.exist");
  });
});

export {};
