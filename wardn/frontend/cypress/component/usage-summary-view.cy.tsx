import usageFixture from "../fixtures/usage-summary.json";

import {
  UsageSummaryView,
  type UsageSummaryResponse,
} from "@/components/organisms/usage-summary-view";

const usage = usageFixture as UsageSummaryResponse;

describe("UsageSummaryView", () => {
  it("renders complete organization metrics, charts, and tabular detail from mock data", () => {
    cy.mount(
      <main className="min-w-0 bg-background p-6 text-foreground">
        <UsageSummaryView mode="organization" usage={usage} />
      </main>
    );

    cy.findByText("Model requests").should("be.visible");
    cy.findAllByText("18").first().should("be.visible");
    cy.findByText("16 succeeded, 2 failed").should("be.visible");
    cy.findAllByText("2,520").first().should("be.visible");
    cy.findAllByText("$0.1842").first().should("be.visible");
    cy.findByText("Daily trend", { exact: true }).should("be.visible");
    cy.findByText("Tool calls by agent", { exact: true }).should("be.visible");
    cy.get(".recharts-wrapper").should("have.length.at.least", 4);
    cy.get(".recharts-pie-sector path").first().should("have.attr", "fill", "#2563eb");
    cy.findByText("owner@example.com").should("be.visible");
    cy.findAllByText("Operations agent").last().should("be.visible");
    cy.document().then((document) => {
      expect(document.documentElement.scrollWidth).to.be.at.most(window.innerWidth);
    });
  });

  it("uses personal labels and omits organization-only user detail", () => {
    cy.mount(
      <main className="min-w-0 bg-background p-6 text-foreground">
        <UsageSummaryView mode="me" usage={{ ...usage, byUser: [] }} />
      </main>
    );

    cy.findByText("My model tokens", { exact: true }).should("be.visible");
    cy.findByText("My workspace tokens", { exact: true }).should("be.visible");
    cy.findByText("My tool calls", { exact: true }).should("be.visible");
    cy.findByText("By user", { exact: true }).should("not.exist");
    cy.findByText("My models", { exact: true }).should("be.visible");
  });

  it("retains readable semantic colors in dark theme", () => {
    cy.document().then((document) => {
      document.documentElement.className = "dark";
      document.documentElement.style.colorScheme = "dark";
    });
    cy.mount(
      <main className="min-w-0 bg-background p-6 text-foreground">
        <UsageSummaryView mode="organization" usage={usage} />
      </main>
    );

    cy.get("main").should("have.css", "background-color", "rgb(11, 15, 20)");
    cy.findByText("Daily trend", { exact: true }).should("be.visible");
    cy.get(".recharts-pie-sector path").first().should("have.attr", "fill", "#2563eb");
  });
});
