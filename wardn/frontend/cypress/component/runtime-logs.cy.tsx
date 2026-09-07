import { useState } from "react";

import { RuntimeLogsButton, RuntimeLogViewer } from "@/components/organisms/runtime-logs";
import type { RuntimeLogPage } from "@/lib/api/generated/model";

const organizationId = "11111111-1111-4111-8111-111111111111";
const jobId = "22222222-2222-4222-8222-222222222222";
const path = `/api/v1/organizations/${organizationId}/runtime-logs/mcp_operation/${jobId}`;
const entry = (id: string, level: "INFO" | "ERROR", message: string) => ({
  id, level, message, timestamp: "2026-09-08T12:00:00Z", fields: { event: "catalog_sync", attempt: 2 },
});
const page: RuntimeLogPage = {
  jobId, jobStatus: "succeeded", items: [entry("1", "INFO", "Catalog sync started")],
  nextCursor: "1", hasMore: false, truncated: false, unreadableEntries: 0,
  retentionSeconds: 604800, maxEntries: 1000,
};

describe("runtime job logs", () => {
  it("drains cursor pages without duplicates and filters, expands, and downloads logs", () => {
    cy.intercept("GET", `${path}*`, (request) => {
      request.reply(request.query.after
        ? { ...page, items: [entry("1", "INFO", "Catalog sync started"), entry("2", "ERROR", "Catalog fetch failed")], nextCursor: "2" }
        : { ...page, hasMore: true });
    }).as("logs");
    cy.mount(<RuntimeLogViewer organizationId={organizationId} kind="mcp_operation" jobId={jobId} />);
    cy.wait("@logs");
    cy.wait("@logs").its("request.query.after").should("equal", "1");
    cy.get("details").should("have.length", 2);
    cy.findByLabelText("Log level").select("ERROR");
    cy.get("details").should("have.length", 1);
    cy.contains("summary", "Catalog fetch failed").click();
    cy.get("details pre").should("be.visible").and("contain.text", '"attempt": 2');
    cy.findByLabelText("Search runtime logs").type("missing");
    cy.findByText("No logs match these filters.").should("be.visible");
    cy.findByRole("button", { name: "Download" }).should("be.disabled");
    cy.findByLabelText("Search runtime logs").clear().type("fetch");
    cy.window().then((window) => {
      cy.stub(window.HTMLAnchorElement.prototype, "click").as("download");
      cy.stub(window.URL, "createObjectURL").as("blob").returns("blob:logs");
    });
    cy.findByRole("button", { name: "Download" }).click();
    cy.get("@download").should("have.been.calledOnce");
    cy.get("@blob").should("have.been.calledOnce");
  });

  it("shows storage errors and permits refresh without treating them as empty history", () => {
    cy.intercept("GET", `${path}*`, { statusCode: 503, body: { detail: "Runtime log storage is temporarily unavailable" } });
    cy.mount(<RuntimeLogViewer organizationId={organizationId} kind="mcp_operation" jobId={jobId} />);
    cy.findByRole("alert").should("contain.text", "Runtime log storage is temporarily unavailable");
    cy.contains("No retained runtime logs").should("not.exist");
    cy.intercept("GET", `${path}*`, { body: page });
    cy.findByRole("button", { name: "Refresh logs" }).click();
    cy.findByRole("alert").should("not.exist");
    cy.contains("Catalog sync started").should("be.visible");
  });

  it("clears previous organization entries immediately when switching scope", () => {
    function SwitchingViewer() {
      const [organization, setOrganization] = useState(organizationId);
      return <><button onClick={() => setOrganization("another")}>Switch organization</button>
        <RuntimeLogViewer organizationId={organization} kind="mcp_operation" jobId={jobId} /></>;
    }
    cy.intercept("GET", `${path}*`, { body: page });
    cy.intercept("GET", "/api/v1/organizations/another/runtime-logs/**", { statusCode: 403, body: { detail: "Forbidden" } });
    cy.mount(<SwitchingViewer />);
    cy.contains("Catalog sync started").should("be.visible");
    cy.findByRole("button", { name: "Switch organization" }).click();
    cy.contains("Catalog sync started").should("not.exist");
    cy.findByRole("alert").should("contain.text", "Organization administrator access is required");
  });

  it("fits the dark mobile dialog and only requests logs while open", () => {
    cy.viewport(390, 844);
    cy.document().then((document) => {
      document.documentElement.className = "dark";
      document.documentElement.style.colorScheme = "dark";
    });
    cy.intercept("GET", `${path}*`, { body: page }).as("logs");
    cy.mount(<RuntimeLogsButton organizationId={organizationId} kind="mcp_operation" jobId={jobId} />);
    cy.get("@logs.all").should("have.length", 0);
    cy.findByRole("button", { name: "Runtime logs" }).click();
    cy.wait("@logs");
    cy.findByRole("dialog").should("be.visible").then(($dialog) => {
      const bounds = $dialog[0].getBoundingClientRect();
      expect(bounds.left).to.be.at.least(0);
      expect(bounds.right).to.be.at.most(390);
    });
    cy.screenshot("runtime-logs-dark-mobile");
    cy.findByRole("button", { name: /^Close$/ }).click();
    cy.findByRole("dialog").should("not.exist");
  });
});
