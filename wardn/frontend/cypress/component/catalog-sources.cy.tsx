import { CatalogSourcesClient } from "@/app/catalog/catalog-sources-client";
import type { MCPCatalogSource } from "@/app/catalog/catalog-source-types";
import type { MCPOperationJobRead } from "@/lib/api/generated/model";

const source: MCPCatalogSource = {
  id: "11111111-1111-4111-8111-111111111111",
  organizationId: "22222222-2222-4222-8222-222222222222",
  name: "Wardn Hub",
  provider: "wardn_hub",
  baseUrl: "https://hub.wardnai.dev",
  tenantId: "",
  syncMode: "latest_only",
  lastError: "",
  isEnabled: true,
  hasAuthToken: true,
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z",
};
const job: MCPOperationJobRead = {
  jobId: "33333333-3333-4333-8333-333333333333",
  organizationId: source.organizationId,
  operation: "sync_catalog_source",
  resourceKey: source.id,
  status: "queued",
  attemptCount: 1,
  maxAttempts: 3,
  cleanupAttemptCount: 0,
  cleanupMaxAttempts: 5,
  cleanupStatus: "not_required",
  progressCurrent: 0,
  progressTotal: 1,
  progressMessage: "Retry scheduled",
  createdAt: source.createdAt,
  updatedAt: source.updatedAt,
};
const basePath = `/api/v1/organizations/${source.organizationId}/mcp/catalog`;

describe("catalog synchronization feedback", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, "", "/catalog");
    cy.document().then((document) => {
      document.documentElement.className = "dark";
      document.documentElement.style.colorScheme = "dark";
    });
  });

  it("clears progress after a gateway failure and allows a successful retry", () => {
    cy.intercept("POST", `${basePath}/sources/${source.id}/sync`, {
      body: job,
      statusCode: 202,
    }).as("sync");
    cy.intercept("GET", `${basePath}/jobs/${job.jobId}`, {
      body: "<html><head><title>502 Bad Gateway</title></head><body>nginx</body></html>",
      headers: { "content-type": "text/html" },
      statusCode: 502,
    }).as("poll");
    cy.mount(<CatalogSourcesClient organizationId={source.organizationId} sources={[source]} />);

    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.wait("@sync");
    cy.findByRole("status").should("contain.text", "Retry scheduled")
      .and("not.have.class", "bg-emerald-50");
    cy.wait("@poll");
    cy.findByRole("alert").should("have.text", "Wardn is temporarily unavailable. Please try again shortly.");
    cy.findByRole("status").should("not.exist");
    cy.get("body").should("not.contain.text", "<html>").and("not.contain.text", "nginx");
    cy.findByRole("button", { name: "Sync Wardn Hub" }).should("be.enabled");
    cy.screenshot("catalog-gateway-error-dark");

    cy.intercept("POST", `${basePath}/sources/${source.id}/sync`, {
      body: {
        ...job,
        status: "succeeded",
        result: { source: { ...source, lastSuccessAt: source.updatedAt }, syncedCount: 12 },
      },
      statusCode: 202,
    });
    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.findByRole("alert").should("not.exist");
    cy.findByRole("status").should("have.text", "Synced 12 server definitions.")
      .and("have.class", "bg-emerald-50");
    cy.findByText("Never synced").should("not.exist");
  });

  it("shows a failed job without a stale success notice", () => {
    cy.intercept("POST", `${basePath}/sources/${source.id}/sync`, {
      body: { ...job, status: "failed", errorMessage: "Catalog authentication failed." },
      statusCode: 202,
    });
    cy.mount(<CatalogSourcesClient organizationId={source.organizationId} sources={[source]} />);

    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.findByRole("alert").should("have.text", "Catalog authentication failed.");
    cy.findByRole("status").should("not.exist");
    cy.findByRole("button", { name: "Sync Wardn Hub" }).should("be.enabled");
  });
});
