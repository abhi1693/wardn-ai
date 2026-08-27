import usageFixture from "../fixtures/usage-summary.json";

import {
  UsageSummaryView,
  type UsageSummaryResponse,
} from "@/components/organisms/usage-summary-view";

const usage = usageFixture as UsageSummaryResponse;

describe("UsageSummaryView", () => {
  beforeEach(() => {
    cy.window().then((window) => {
      for (const key of Object.keys(window.localStorage)) {
        if (key.startsWith("wardn.usage.sections.")) {
          window.localStorage.removeItem(key);
        }
      }
    });
  });

  it("renders complete organization metrics, charts, and tabular detail from mock data", () => {
    cy.mount(
      <main className="min-w-0 bg-background p-6 text-foreground">
        <UsageSummaryView
          attentionActionLabel="Review workspace observability"
          attentionHref="/observability"
          mode="organization"
          usage={usage}
        />
      </main>
    );

    cy.findByText("Needs attention", { exact: true }).should("be.visible");
    cy.findByText("Usage overview", { exact: true }).should("be.visible");
    cy.findByText("Needs attention", { exact: true }).then(($attention) => {
      cy.findByText("Usage overview", { exact: true }).then(($overview) => {
        expect(
          $attention[0].compareDocumentPosition($overview[0]) &
            Node.DOCUMENT_POSITION_FOLLOWING
        ).to.be.greaterThan(0);
      });
    });
    cy.findByText("2 failed model requests").should("be.visible");
    cy.findByRole("link", { name: "Review workspace observability" }).should("be.visible");
    cy.findByText("Model requests").should("be.visible");
    cy.findAllByText("18").first().should("be.visible");
    cy.findByText("16 succeeded, 2 failed").should("be.visible");
    cy.findAllByText("2,520").first().should("be.visible");
    cy.findAllByText("$0.1842").first().should("be.visible");
    cy.findByText("Daily trend", { exact: true }).should("be.visible");
    cy.findByText("Tool calls by agent", { exact: true }).should("be.visible");
    cy.findAllByText("One contributor", { exact: true }).should("have.length", 2);
    cy.get(".recharts-wrapper").should("have.length", 2);
    cy.get(".recharts-pie-sector path").first().should("have.attr", "fill", "#2563eb");
    cy.findByText("owner@example.com").should("not.exist");
    cy.findByRole("button", { name: "Expand Detailed breakdowns" }).click();
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
    cy.findByRole("button", { name: "Expand Detailed breakdowns" }).click();
    cy.findByText("My models", { exact: true }).should("be.visible");
  });

  it("remembers expanded sections across remounts", () => {
    const mountView = () =>
      cy.mount(
        <main className="min-w-0 bg-background p-6 text-foreground">
          <UsageSummaryView mode="organization" usage={usage} />
        </main>
      );

    mountView();
    cy.findByRole("button", { name: "Expand Detailed breakdowns" }).click();
    cy.window().then((window) => {
      expect(
        window.localStorage.getItem("wardn.usage.sections.organization.breakdowns")
      ).to.equal("open");
    });

    mountView();
    cy.findByRole("button", { name: "Collapse Detailed breakdowns" }).should("be.visible");
    cy.findByText("owner@example.com").should("be.visible");
  });

  it("uses compact summaries instead of charts for one or zero data points", () => {
    cy.mount(
      <main className="min-w-0 bg-background p-6 text-foreground">
        <UsageSummaryView
          mode="organization"
          usage={{
            ...usage,
            byAgent: usage.byAgent.slice(0, 1),
            daily: usage.daily.slice(0, 1),
            summary: { ...usage.summary, failed: 0, running: 0 },
          }}
        />
      </main>
    );

    cy.findByRole("button", { name: "Expand Needs attention" }).should("be.visible");
    cy.findByRole("button", { name: "Expand Usage trends" }).click();
    cy.get(".recharts-wrapper").should("not.exist");
    cy.findByText("One recorded day", { exact: true }).should("be.visible");
    cy.findAllByText("One contributor", { exact: true }).should("have.length", 2);
    cy.findByText("One contributing agent", { exact: true }).should("be.visible");
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
