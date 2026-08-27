const organizationId = "org-1";
const workspaceId = "workspace-1";
const runsPath = `/org/${organizationId}/workspace/${workspaceId}/agent-runs`;

function agentRun(index: number) {
  const status = index % 3 === 0 ? "failed" : index % 2 === 0 ? "running" : "succeeded";
  return {
    agentId: "agent-1",
    canCancel: status === "running",
    canRerun: status === "failed",
    conversationId: `conversation-${index}`,
    costUsd: "0.0100",
    createdAt: "2026-06-30T00:00:00.000Z",
    error: status === "failed" ? "Runtime failed." : "",
    finishedAt: status === "running" ? null : "2026-06-30T00:00:00.000Z",
    id: `run-${String(index).padStart(2, "0")}`,
    inputTokens: index * 100,
    organizationId,
    outputTokens: index * 20,
    startedAt: `2026-06-${String(Math.max(1, 30 - index)).padStart(2, "0")}T00:00:00.000Z`,
    status,
    toolCalls: index,
    totalTokens: index * 120,
    triggerType: index % 2 === 0 ? "scheduled" : "chat",
    updatedAt: "2026-06-30T00:00:00.000Z",
    workspaceId,
  };
}

describe("operational data surfaces", () => {
  beforeEach(() => {
    cy.resetBackend({ agentRuns: Array.from({ length: 23 }, (_, index) => agentRun(index + 1)) });
    cy.login();
    cy.viewport(1280, 720);
  });

  it("filters, paginates, restores, and configures the runs table", () => {
    cy.visit(runsPath);
    cy.findByRole("heading", { level: 1, name: "Runs" }).should("be.visible");
    cy.findByText("Page 1 of 2").should("be.visible");
    cy.assertDesktopFit();
    cy.findByRole("link", { name: "Open run run-01" }).should("be.visible");
    cy.findByRole("button", { name: "More actions for run-01" }).click();
    cy.findByRole("menuitem", { name: "Open chat" }).should("be.visible");
    cy.findByRole("button", { name: "Cancel run" }).should("not.exist");
    cy.get("body").type("{esc}");

    cy.findByRole("button", { name: "More actions for run-02" }).click();
    cy.findByRole("menuitem", { name: "Cancel run" }).click();
    cy.findByRole("alertdialog", { name: "Cancel this run?" }).should("be.visible");
    cy.findByRole("button", { name: "Cancel" }).click();
    cy.findByRole("alertdialog", { name: "Cancel this run?" }).should("not.exist");
    cy.screenshot("operational-runs-table", { capture: "viewport" });
    cy.findByRole("button", { name: "Next page" }).click();
    cy.findByText("Page 2 of 2").should("be.visible");
    cy.location("search").should("contain", "runs-page=2");

    cy.findByLabelText("Search run ID or trigger").type("run-21");
    cy.findByText("run-21").should("be.visible");
    cy.findByText("1 records").should("be.visible");
    cy.location("search").should("contain", "runs-query=run-21");

    cy.reload();
    cy.findByLabelText("Search run ID or trigger").should("have.value", "run-21");
    cy.findByText("run-21").should("be.visible");

    cy.findByRole("button", { name: "Columns" }).click();
    cy.findByRole("menuitemcheckbox", { name: "totalTokens" }).click();
    cy.findByRole("columnheader", { name: "Tokens" }).should("not.exist");
    cy.location("search").should("contain", "runs-hidden=totalTokens");
    cy.assertDesktopFit();
  });
});

export {};
