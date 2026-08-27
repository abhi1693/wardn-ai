const organizationId = "org-1";
const workspaceId = "workspace-1";
const workspaceBasePath = `/org/${organizationId}/workspace/${workspaceId}`;

function stabilizePage() {
  cy.document().then(async (document) => {
    await document.fonts.ready;
    const style = document.createElement("style");
    style.textContent = `
      *, *::before, *::after {
        animation: none !important;
        caret-color: transparent !important;
        transition: none !important;
      }
    `;
    document.head.append(style);
  });
  cy.wait(100);
}

describe("desktop visual regression", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
    cy.viewport(1280, 720);
  });

  it("matches the operational shell and table in both themes", () => {
    cy.visit(`${workspaceBasePath}/agent-runs`);
    cy.findByRole("heading", { level: 1, name: "Runs" }).should("be.visible");
    stabilizePage();
    cy.compareSnapshot("runs-shell-table-light");

    cy.findByRole("button", { name: "Switch to dark theme" }).click();
    cy.get("html").should("have.class", "dark");
    stabilizePage();
    cy.compareSnapshot("runs-shell-table-dark");
  });

  it("matches the dynamically loaded provider form", () => {
    cy.visit(`${workspaceBasePath}/chat-providers/new`);
    cy.findByRole("heading", { level: 1, name: "New Chat Provider" }).should("be.visible");
    cy.findByLabelText(/Name/).should("be.visible");
    stabilizePage();
    cy.compareSnapshot("provider-form-light");
  });

  it("matches a complete scheduled-task empty state", () => {
    cy.visit(`${workspaceBasePath}/scheduled-tasks`);
    cy.findByText("No scheduled tasks").should("be.visible");
    cy.findAllByRole("link", { name: "New task" }).should("have.length", 2);
    stabilizePage();
    cy.compareSnapshot("scheduled-tasks-empty-light");
  });

  it("matches destructive confirmation focus and hierarchy", () => {
    cy.visit(`${workspaceBasePath}/agent-runs`);
    cy.findByRole("button", { name: "More actions for run-02" }).click();
    cy.findByRole("menuitem", { name: "Cancel run" }).click();
    cy.findByRole("alertdialog", { name: "Cancel this run?" }).should("be.visible");
    cy.findByRole("button", { name: "Cancel" }).should("have.focus");
    stabilizePage();
    cy.compareSnapshot("cancel-run-dialog-light");
  });
});

export {};
