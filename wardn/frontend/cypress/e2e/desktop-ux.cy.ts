export {};

const organizationId = "org-1";
const workspaceId = "workspace-1";
const sidebarPreferenceKey = "wardn.sidebar.mode";

const routes = [
  { name: "workspaces", path: `/org/${organizationId}/workspaces`, title: "Workspaces" },
  { name: "usage", path: `/org/${organizationId}/usage`, title: "Usage" },
  {
    name: "connections",
    path: `/org/${organizationId}/workspace/${workspaceId}/install/new`,
    title: "Add Connection",
  },
  {
    name: "skills",
    path: `/org/${organizationId}/workspace/${workspaceId}/skills`,
    title: "Skill Marketplace",
  },
  { name: "catalog", path: `/org/${organizationId}/catalog/new`, title: "New source" },
] as const;

function verifyRoute(route: (typeof routes)[number], theme: "light" | "dark") {
  cy.visit(route.path);
  cy.findByRole("heading", { level: 1, name: route.title }).should("be.visible");
  cy.findByRole("navigation", { name: "Primary" }).should("be.visible");
  cy.findByRole("button", { name: `Switch to ${theme === "light" ? "dark" : "light"} theme` }).should(
    "be.visible"
  );
  cy.get("html").should("have.class", theme);
  if (route.name === "usage") {
    cy.get(".recharts-wrapper").first().should("be.visible");
    cy.get(".recharts-pie-sector path").first().should("have.attr", "fill", "#2563eb");
  }
  cy.assertDesktopFit();
  cy.screenshot(`${theme}-${route.name}`, { capture: "fullPage" });
}

describe("desktop UX details", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
    cy.viewport(1440, 900);
  });

  it("keeps core workflows within the viewport with clear shell controls", () => {
    routes.forEach((route) => verifyRoute(route, "light"));
    cy.visit(routes[2].path);
    cy.findByRole("button", { name: "Select Google Search Console" }).click();
    cy.findByText("Connection Source", { exact: true }).should("be.visible");
    cy.findByRole("button", { name: "Add" }).should("be.visible");
    cy.assertDesktopFit();
  });

  it("persists dark theme across forms, tables, and navigation", () => {
    cy.visit(routes[0].path);
    cy.findByRole("button", { name: "Switch to dark theme" }).click();
    cy.get("html").should("have.class", "dark");
    cy.window().its("localStorage.theme").should("equal", "dark");
    routes.forEach((route) => verifyRoute(route, "dark"));
    cy.reload();
    cy.get("html").should("have.class", "dark");
  });

  it("remembers a compact sidebar that fits a laptop viewport", () => {
    cy.viewport(1280, 720);
    cy.visit(`/org/${organizationId}/workspace/${workspaceId}/agent-runs`);

    cy.findByRole("button", { name: "Collapse sidebar" }).click();
    cy.get('aside[data-sidebar-mode="compact"]').should("have.css", "width", "72px");
    cy.window().then((window) => {
      expect(window.localStorage.getItem(sidebarPreferenceKey)).to.equal("compact");
    });
    cy.get('[data-testid="sidebar-navigation-scroll"]').then(($navigation) => {
      const navigation = $navigation[0];
      expect(navigation.scrollHeight).to.be.at.most(navigation.clientHeight);
    });
    cy.findByRole("link", { name: "Scheduled Tasks" }).focus();
    cy.findByRole("tooltip").should("contain.text", "Scheduled Tasks");
    cy.assertDesktopFit();

    cy.reload();
    cy.findByRole("button", { name: "Expand sidebar" }).should("be.visible");
    cy.get('aside[data-sidebar-mode="compact"]').should("have.css", "width", "72px");

    cy.findByRole("button", { name: "Expand sidebar" }).click();
    cy.get('aside[data-sidebar-mode="expanded"]').should("have.css", "width", "260px");
    cy.window().then((window) => {
      expect(window.localStorage.getItem(sidebarPreferenceKey)).to.equal("expanded");
    });
  });
});
