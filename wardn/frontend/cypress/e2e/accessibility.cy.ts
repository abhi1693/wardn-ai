const organizationId = "org-1";
const workspaceId = "workspace-1";

const routes = [
  {
    path: `/org/${organizationId}/workspaces`,
    title: "Workspaces",
  },
  {
    path: `/org/${organizationId}/workspace/${workspaceId}/agent-runs`,
    title: "Runs",
  },
  {
    path: `/org/${organizationId}/workspace/${workspaceId}/chat-providers/new`,
    title: "New Chat Provider",
  },
  {
    path: `/org/${organizationId}/workspace/${workspaceId}/scheduled-tasks`,
    title: "Scheduled Tasks",
  },
] as const;

function setTheme(theme: "dark" | "light") {
  return (window: Window) => {
    window.localStorage.setItem("theme", theme);
  };
}

function checkWcag() {
  cy.injectAxe();
  cy.checkA11y(undefined, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    },
  }, (violations) => {
    if (violations.length > 0) {
      throw new Error(
        violations
          .map(
            (violation) =>
              `${violation.id}: ${violation.nodes
                .map((node) => node.target.join(" "))
                .join(", ")}`
          )
          .join("\n")
      );
    }
  });
}

describe("desktop accessibility", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
    cy.viewport(1280, 720);
  });

  for (const theme of ["light", "dark"] as const) {
    for (const route of routes) {
      it(`${route.title} has no detectable WCAG A/AA violations in ${theme} theme`, () => {
        cy.visit(route.path, { onBeforeLoad: setTheme(theme) });
        cy.findByRole("heading", { level: 1, name: route.title }).should("be.visible");
        cy.get("html").should("have.class", theme);
        cy.assertDesktopFit();
        checkWcag();
      });
    }
  }

  it("keeps the destructive confirmation keyboard accessible", () => {
    cy.visit(`/org/${organizationId}/workspace/${workspaceId}/agent-runs`);
    cy.findByRole("button", { name: "More actions for run-02" }).click();
    cy.findByRole("menuitem", { name: "Cancel run" }).click();
    cy.findByRole("alertdialog", { name: "Cancel this run?" }).should("be.visible");
    cy.findByRole("button", { name: "Cancel" }).should("have.focus");
    checkWcag();
  });
});

export {};
