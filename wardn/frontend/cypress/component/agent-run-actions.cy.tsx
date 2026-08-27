import { AgentRunActions } from "@/app/org/[organizationId]/workspace/[workspaceId]/agent-runs/agent-run-actions";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

function routerContext() {
  return {
    back: cy.stub(),
    forward: cy.stub(),
    prefetch: cy.stub(),
    push: cy.stub(),
    refresh: cy.stub(),
    replace: cy.stub(),
  };
}

describe("agent run row actions", () => {
  it("keeps one overflow trigger and confirms secondary run actions", () => {
    cy.mount(
      <AppRouterContext.Provider value={routerContext()}>
        <AgentRunActions
          canCancel
          canRerun
          chatHref="/org/org-1/workspace/workspace-1/chat/conversation-1"
          organizationId="org-1"
          runId="run-1"
          variant="menu"
          workspaceId="workspace-1"
        />
      </AppRouterContext.Provider>
    );

    cy.findAllByRole("button").should("have.length", 1);
    cy.findByRole("button", { name: "More actions for run-1" }).click();
    cy.findByRole("menuitem", { name: "Open chat" })
      .should("have.attr", "href")
      .and("include", "/chat/conversation-1");
    cy.findByRole("menuitem", { name: "Rerun" }).should("be.visible");
    cy.findByRole("menuitem", { name: "Cancel run" }).click();

    cy.findByRole("alertdialog", { name: "Cancel this run?" }).should("be.visible");
    cy.findByRole("button", { name: "Cancel" }).click();

    cy.findByRole("button", { name: "More actions for run-1" }).click();
    cy.findByRole("menuitem", { name: "Rerun" }).click();
    cy.findByRole("alertdialog", { name: "Rerun this run?" }).should("be.visible");
  });
});
