export {};

const organizationId = "org-1";
const workspaceId = "workspace-1";

describe("frontend API proxy", () => {
  beforeEach(() => cy.resetBackend());

  it("forwards agent approval decisions through same-origin /api/v1", () => {
    const approvalId = "11111111-1111-4111-8111-111111111111";
    cy.request("POST", `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/agents/agent-1/tool-approvals/${approvalId}`, {
      decision: "deny",
    }).then(({ body, status }) => {
      expect(status).to.equal(200);
      expect(body).to.include({
        approvalId,
        error: "Denied by user.",
        status: "denied",
        toolName: "namespace_list",
      });
    });

    cy.backendRequests().then((requests) => {
      const approvalRequest = requests.find(
        (entry) =>
          entry.method === "POST" &&
          entry.path ===
            `/api/v1/organizations/${organizationId}/workspaces/${workspaceId}/agents/agent-1/tool-approvals/${approvalId}`
      );
      expect(approvalRequest?.body).to.deep.include({ decision: "deny" });
    });
  });
});

describe("OIDC authentication", () => {
  it("completes OIDC through the same-origin login and callback bridge", () => {
    cy.resetBackend({ authMode: "oidc" });
    cy.visit("/login?error=oidc&next=%2Forg");
    cy.findByRole("button", { name: "Sign in with Zitadel" }).click();
    cy.url().should("include", "/favicon.ico?oidc-provider=1");
    cy.getCookie("wardn_oidc_state_test").should("include", {
      name: "wardn_oidc_state_test",
      value: "state-cookie",
    });

    cy.visit("/api/auth/oidc/callback?code=test-code&state=test-state");
    cy.location("pathname").should("equal", "/org");
    cy.env(["sessionCookieName"]).then(({ sessionCookieName }) => {
      cy.getCookie(String(sessionCookieName)).should("include", {
        value: "test-session",
      });
    });
    cy.getCookie("wardn_oidc_state_test").should("be.null");
  });

  it("moves OIDC login to the configured canonical origin before setting state", () => {
    cy.request({
      followRedirect: false,
      headers: {
        "x-forwarded-host": "alternate.example.com",
        "x-forwarded-proto": "http",
      },
      url: "/api/auth/oidc/login?redirectTo=%2Forg",
    }).then((response) => {
      expect(response.status).to.equal(307);
      expect(response.redirectedToUrl).to.equal(
        `${Cypress.config("baseUrl")}/api/auth/oidc/login?redirectTo=%2Forg`
      );
      expect(response.headers).not.to.have.property("set-cookie");
    });
  });
});

describe("workspace chat", () => {
  it("renders the shell while quick-start runs, then opens the conversation", () => {
    cy.resetBackend({ quickStartDelayMs: 800 });
    cy.login();
    cy.visit(`/org/${organizationId}/workspace/${workspaceId}/chat`);

    cy.findByRole("heading", { name: "Chat" }).should("be.visible");
    cy.findByText("Starting workspace chat", { exact: true }).should("be.visible");
    cy.location("pathname", { timeout: 10_000 }).should(
      "equal",
      `/org/${organizationId}/workspace/${workspaceId}/chat/conversation-1`
    );
    cy.findByPlaceholderText("Message this workspace").should("be.visible");
    cy.backendRequests().then((requests) => {
      expect(
        requests.filter(
          (entry) => entry.method === "POST" && entry.path.endsWith("/agents/quick-start")
        )
      ).to.have.length(1);
    });
  });
});
