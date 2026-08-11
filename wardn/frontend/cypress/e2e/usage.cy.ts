export {};

const organizationId = "org-1";

describe("usage summary scope", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
  });

  it("combines organization and personal usage under a scope filter", () => {
    cy.visit(`/org/${organizationId}/usage`);

    cy.findByRole("heading", { name: "Usage" }).should("be.visible");
    cy.findByRole("navigation", { name: "Primary" })
      .findByRole("link", { name: "My Usage" })
      .should("not.exist");
    cy.findByRole("tab", { name: "Organization" }).should(
      "have.attr",
      "aria-selected",
      "true"
    );
    cy.findByText("Organization usage by user, workspace, agent, and model").should("be.visible");
    cy.findByText("By user", { exact: true }).should("be.visible");

    cy.findByRole("tab", { name: "My usage" }).click();
    cy.location("search").should("equal", "?scope=me");
    cy.findByRole("tab", { name: "My usage" }).should("have.attr", "aria-selected", "true");
    cy.findByText("Your attributed model requests, tokens, cost, and tool calls").should(
      "be.visible"
    );
    cy.findByText("My models", { exact: true }).should("be.visible");

    cy.backendRequests().then((requests) => {
      expect(
        requests.filter((entry) => entry.path.includes("/usage")).map((entry) => entry.path)
      ).to.deep.equal([
        `/api/v1/organizations/${organizationId}/usage/summary`,
        "/api/v1/me/usage",
      ]);
    });
  });

  it("applies top usage filters and preserves them across scope changes", () => {
    cy.visit(`/org/${organizationId}/usage`);
    cy.findByLabelText("Start date").clear();
    cy.findByLabelText("Start date").type("2026-06-01");
    cy.findByLabelText("End date").clear();
    cy.findByLabelText("End date").type("2026-06-30");
    cy.findByLabelText("Rows").select("50");
    cy.findByRole("button", { name: "Apply" }).click();

    cy.location("search").should((search) => {
      const params = new URLSearchParams(search);
      expect(params.get("scope")).to.equal("organization");
      expect(params.get("startDate")).to.equal("2026-06-01");
      expect(params.get("endDate")).to.equal("2026-06-30");
      expect(params.get("breakdownLimit")).to.equal("50");
    });
    cy.findByLabelText("Start date").should("have.value", "2026-06-01");
    cy.findByLabelText("End date").should("have.value", "2026-06-30");

    cy.findByRole("tab", { name: "My usage" }).click();
    cy.location("search").should((search) => {
      const params = new URLSearchParams(search);
      expect(params.get("scope")).to.equal("me");
      expect(params.get("startDate")).to.equal("2026-06-01");
      expect(params.get("endDate")).to.equal("2026-06-30");
      expect(params.get("breakdownLimit")).to.equal("50");
    });
  });
});
