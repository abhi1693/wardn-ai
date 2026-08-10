const organizationId = "org-1";
const workspaceId = "workspace-1";
const runsPath = `/org/${organizationId}/workspace/${workspaceId}/agent-runs`;

function agentRun(index: number) {
  return {
    agentId: "agent-1",
    canCancel: false,
    canRerun: false,
    conversationId: `conversation-${index}`,
    costUsd: "0.0100",
    createdAt: "2026-06-30T00:00:00.000Z",
    error: "",
    finishedAt: "2026-06-30T00:00:00.000Z",
    id: `run-${index}`,
    inputTokens: 100,
    organizationId,
    outputTokens: 20,
    startedAt: "2026-06-30T00:00:00.000Z",
    status: "succeeded",
    toolCalls: 1,
    totalTokens: 120,
    triggerType: "chat",
    updatedAt: "2026-06-30T00:00:00.000Z",
    workspaceId,
  };
}

describe("frontend performance budgets", () => {
  beforeEach(() => {
    cy.resetBackend({ agentRuns: Array.from({ length: 500 }, (_, index) => agentRun(index + 1)) });
    cy.login();
    cy.viewport(1280, 720);
  });

  it("renders a large operational dataset with bounded work and stable layout", () => {
    const startedAt = Date.now();
    cy.visit(runsPath);
    cy.findByRole("heading", { level: 1, name: "Runs" })
      .should("be.visible")
      .then(() => expect(Date.now() - startedAt).to.be.lessThan(10_000));
    cy.findByText("500 records").should("be.visible");
    cy.get("tbody tr").should("have.length", 20);
    cy.get("main")
      .invoke("text")
      .should("match", /Runs[\s\S]+Recent Runs/);
    cy.assertDesktopFit();

    cy.findByRole("heading", { level: 1, name: "Runs" }).then(($heading) => {
      const initial = $heading[0].getBoundingClientRect();
      cy.wait(250);
      cy.findByRole("heading", { level: 1, name: "Runs" }).then(($settledHeading) => {
        const settled = $settledHeading[0].getBoundingClientRect();
        expect(Math.abs(settled.x - initial.x)).to.be.lessThan(1);
        expect(Math.abs(settled.y - initial.y)).to.be.lessThan(1);
        expect(Math.abs(settled.width - initial.width)).to.be.lessThan(1);
        expect(Math.abs(settled.height - initial.height)).to.be.lessThan(1);
      });
    });
  });

  it("accepts bounded metrics and rejects invalid telemetry payloads", () => {
    cy.request("POST", "/api/frontend-telemetry", {
      kind: "navigation",
      name: "route-transition",
      path: runsPath,
      value: 12.5,
    }).its("status").should("equal", 204);

    cy.request({
      body: { kind: "unknown", name: "invalid", value: -1 },
      failOnStatusCode: false,
      method: "POST",
      url: "/api/frontend-telemetry",
    }).its("status").should("equal", 400);
  });
});

export {};
