export {};

const organizationId = "org-1";
const workspacesPath = `/org/${organizationId}/workspaces`;

describe("desktop route foundation", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
    cy.viewport(1440, 900);
  });

  it("opens the context-aware command menu and navigates with the keyboard", () => {
    cy.visit(workspacesPath);
    cy.findByRole("heading", { level: 1, name: "Workspaces" }).should("be.visible");

    cy.get("body").type("{ctrl}k");
    cy.findByRole("dialog", { name: "Command menu" }).should("be.visible");
    cy.findByRole("combobox", { name: "Search destinations" }).type("usage{enter}");

    cy.location("pathname").should("equal", `/org/${organizationId}/usage`);
    cy.findByRole("heading", { level: 1, name: "Usage" }).should("be.visible");
    cy.assertDesktopFit();
  });

  it("keeps every header action visible at a compact desktop width", () => {
    cy.viewport(1280, 800);
    cy.visit(workspacesPath);

    cy.findByRole("button", { name: "Open command menu" }).should("be.visible");
    cy.findByRole("link", { name: "New workspace" }).should("be.visible");
    cy.findByRole("button", { name: "Switch to dark theme" }).should("be.visible");
    cy.findByRole("button", { name: "Sign out" }).should("be.visible");
    cy.assertDesktopFit();
  });

  it("keeps the workspace shell mounted during a delayed navigation", () => {
    cy.visit(`/org/${organizationId}/workspace/workspace-1/skills`);
    cy.findByRole("heading", { level: 1, name: "Skill Marketplace" }).should("be.visible");
    cy.resetBackend({ organizationsDelayMs: 800 });

    cy.get("aside").then(($initialSidebar) => {
      cy.get("body").type("{ctrl}k");
      cy.findByRole("combobox", { name: "Search destinations" }).type("connections{enter}");
      cy.findByRole("status", { name: "Loading workspace" }).should("be.visible");
      cy.get("aside").should(($currentSidebar) => {
        expect($currentSidebar[0]).to.equal($initialSidebar[0]);
      });
      cy.findByRole("heading", { level: 1, name: "Connections" }).should("be.visible");
    });
  });

  it("recovers from an organization route failure after retry", () => {
    cy.resetBackend({ organizationsStatus: 500 });
    cy.visit(`/org/${organizationId}/usage`, { failOnStatusCode: false });
    cy.findByRole("alert").should("contain.text", "Organization unavailable");

    cy.resetBackend();
    cy.findByRole("button", { name: "Try again" }).click();
    cy.findByRole("heading", { level: 1, name: "Usage" }).should("be.visible");
  });
});
