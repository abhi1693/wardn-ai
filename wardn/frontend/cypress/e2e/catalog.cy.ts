import type { BackendRequest } from "../support/e2e";

const organizationId = "org-1";

function openAuthenticated(path: string) {
  cy.login();
  cy.visit(path);
}

function resetCatalog(sources?: unknown[], overrides: Record<string, unknown> = {}) {
  return cy.resetBackend({
    ...overrides,
    ...(sources === undefined ? {} : { sources }),
  });
}

function findRequest(
  requests: BackendRequest[],
  method: string,
  path: string
) {
  return requests.find((entry) => entry.method === method && entry.path === path);
}

describe("catalog source management", () => {
  beforeEach(() => resetCatalog());

  it("creates a Wardn Hub source from only the Hub URL and token", () => {
    resetCatalog([]);
    openAuthenticated(`/org/${organizationId}/catalog/new`);
    cy.findByRole("heading", { name: "New Catalog Source" }).should("be.visible");
    cy.findByLabelText("Hub URL").should("have.value", "https://hub.wardnai.dev");
    cy.findByLabelText("Secret backend").should("contain.text", "k3s wardn");
    cy.findByLabelText("Name").type("Production Hub");
    cy.findByLabelText("API token").type("hub-token");
    cy.findByRole("button", { name: "Create source" }).click();

    cy.location("pathname").should("equal", `/org/${organizationId}/catalog`);
    cy.findByRole("article", { name: /Production Hub catalog source/ })
      .should("be.visible")
      .and("contain.text", "hub.wardnai.dev")
      .and("not.contain.text", "Token stored");
    cy.backendRequests().then((requests) => {
      const request = findRequest(
        requests,
        "POST",
        `/api/v1/organizations/${organizationId}/mcp/catalog/sources`
      );
      expect(request?.body).to.deep.include({
        apiToken: "hub-token",
        apiTokenSecretStoreId: "store-1",
        baseUrl: "https://hub.wardnai.dev",
        provider: "wardn_hub",
      });
    });
  });

  it("keeps the existing token when editing without entering a token", () => {
    openAuthenticated(`/org/${organizationId}/catalog/edit/source-1`);
    cy.findByRole("heading", { name: "Edit Catalog Source" }).should("be.visible");
    cy.findByLabelText("API token").should(
      "have.attr",
      "placeholder",
      "Leave blank to keep current token"
    );
    cy.findByLabelText("Name").clear();
    cy.findByLabelText("Name").type("Wardn Hub Production");
    cy.findByRole("button", { name: "Save changes" }).click();
    cy.location("pathname").should("equal", `/org/${organizationId}/catalog`);
    cy.findByRole("article", { name: "Wardn Hub Production catalog source" }).should(
      "be.visible"
    );

    cy.backendRequests().then((requests) => {
      const request = findRequest(
        requests,
        "PATCH",
        `/api/v1/organizations/${organizationId}/mcp/catalog/sources/source-1`
      );
      expect(request?.body).to.deep.include({
        baseUrl: "https://hub.wardnai.dev",
        name: "Wardn Hub Production",
        provider: "wardn_hub",
      });
      expect(request?.body).not.to.have.property("apiToken");
    });
  });

  it("polls, syncs, and deletes a catalog source", () => {
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.findByRole("article", { name: "Wardn Hub catalog source" }).should("be.visible");
    cy.findByLabelText("1 total").should("be.visible");
    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.findByRole("status").should("contain.text", "Synced 2 server definitions.");
    cy.findByRole("article", { name: "Wardn Hub catalog source" }).should("contain.text", "Jun 30");
    cy.backendRequests().then((requests) => {
      expect(requests.filter((entry) => entry.path.includes("/mcp/catalog/jobs/"))).to.have.length(2);
    });

    cy.findByRole("button", { name: "Delete Wardn Hub" }).click();
    cy.findByRole("status").should("contain.text", "Catalog source deleted.");
    cy.findByLabelText("0 total").should("be.visible");
    cy.findByText("No catalog sources in view").should("be.visible");
  });

  it("stops polling a catalog job after navigation", () => {
    resetCatalog(undefined, { catalogJobPollsBeforeSuccess: 100 });
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.intercept("GET", "**/mcp/catalog/jobs/**").as("catalogJob");
    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.wait("@catalogJob");
    cy.findByRole("button", { name: "Edit Wardn Hub" }).should("be.disabled");
    cy.visit("/org");

    cy.backendRequests().then((before) => {
      const count = before.filter((entry) => entry.path.includes("/mcp/catalog/jobs/")).length;
      expect(count).to.be.greaterThan(0);
      cy.wait(2_000);
      cy.backendRequests().then((after) => {
        expect(after.filter((entry) => entry.path.includes("/mcp/catalog/jobs/")).length).to.equal(
          count
        );
      });
    });
  });

  it("loads workspaces only for the organization selected by the route", () => {
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.findByRole("heading", { name: "Catalog" }).should("be.visible");
    cy.backendRequests().then((requests) => {
      const workspaceRequests = requests.filter((entry) => entry.path.endsWith("/workspaces"));
      expect(workspaceRequests).to.have.length(1);
      expect(workspaceRequests[0]).to.include({
        method: "GET",
        path: `/api/v1/organizations/${organizationId}/workspaces`,
      });
    });
  });

  it("displays the first workspace's actual name", () => {
    openAuthenticated(`/org/${organizationId}/workspaces`);
    cy.findByRole("article", { name: "Platform workspace" })
      .findByRole("heading", { name: "Platform" })
      .should("be.visible");
    cy.findByText("Default Workspace", { exact: true }).should("not.exist");
  });

  it("redirects protected catalog pages to login without a session", () => {
    cy.visit(`/org/${organizationId}/catalog`);
    cy.location("pathname").should("equal", "/login");
    cy.location("search").should("include", "next=");
    cy.findByRole("button", { name: "Sign in" }).should("be.visible");
  });

  it("redirects an expired backend session to reauthentication", () => {
    resetCatalog(undefined, { organizationsStatus: 401 });
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.location("pathname").should("equal", "/login");
    cy.location("search").should("include", "reauth=1");
    cy.findByRole("button", { name: "Sign in" }).should("be.visible");
  });

  it("reauthenticates browser API operations after session expiry", () => {
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.findByRole("article", { name: "Wardn Hub catalog source" }).should("be.visible");
    resetCatalog(undefined, { catalogStatus: 401 });
    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.location("pathname").should("equal", "/login");
    cy.location("search").should("include", "reauth=1");
  });

  it("announces catalog operation failures", () => {
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.findByRole("article", { name: "Wardn Hub catalog source" }).should("be.visible");
    resetCatalog(undefined, { catalogStatus: 500 });
    cy.findByRole("button", { name: "Sync Wardn Hub" }).click();
    cy.findByRole("alert").should("contain.text", "catalog request failed");
  });

  it("shows retryable API failures instead of an empty catalog", () => {
    resetCatalog(undefined, { catalogStatus: 503 });
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.findByRole("heading", { name: "Organization unavailable" }).should("be.visible");
    cy.findByRole("button", { name: "Try again" }).should("be.visible");
    cy.findByText("No catalog sources").should("not.exist");
  });

  it("preserves forbidden and not-found backend responses", () => {
    resetCatalog(undefined, { catalogStatus: 403 });
    openAuthenticated(`/org/${organizationId}/catalog`);
    cy.findByRole("heading", { name: "Access denied" }).should("be.visible");

    resetCatalog(undefined, { catalogStatus: 404 });
    cy.visit(`/org/${organizationId}/catalog`);
    cy.findByRole("heading", { name: "Page not found" }).should("be.visible");
  });

  it("reveals a new API token without writing it to browser storage", () => {
    openAuthenticated(`/org/${organizationId}/tokens/new`);
    cy.findByText("Create Gateway Token", { exact: true }).should("be.visible");
    cy.findByRole("button", { name: "Create token" }).click();
    cy.findByText("Token created", { exact: true }).should("be.visible");
    cy.findByRole("textbox", { name: "Token" }).should("have.value", "wardn_test_secret_token");
    cy.window().then((window) => {
      expect(Object.keys(window.localStorage)).to.deep.equal([]);
      expect(Object.keys(window.sessionStorage)).to.deep.equal([]);
    });
    cy.reload();
    cy.findByText("Create Gateway Token", { exact: true }).should("be.visible");
    cy.findByText("wardn_test_secret_token").should("not.exist");
  });

  it("serves browser security headers", () => {
    cy.request("/login").then((response) => {
      expect(response.headers["content-security-policy"]).to.include("default-src 'self'");
      expect(response.headers["content-security-policy"]).to.include("frame-ancestors 'none'");
      expect(response.headers["x-frame-options"]).to.equal("DENY");
      expect(response.headers["x-content-type-options"]).to.equal("nosniff");
      expect(response.headers["referrer-policy"]).to.equal("no-referrer");
      expect(response.headers["permissions-policy"]).to.include("camera=()");
    });
  });
});

describe("catalog source visual details", () => {
  beforeEach(() => {
    resetCatalog();
    cy.login();
    cy.viewport(1280, 720);
  });

  it("keeps the source form aligned and usable on desktop", () => {
    cy.visit(`/org/${organizationId}/catalog/new`);
    cy.findByRole("heading", { name: "New Catalog Source" }).should("be.visible");
    cy.findByLabelText("Hub URL").should("be.visible");
    cy.findByLabelText("API token").should("be.visible");
    cy.findByRole("button", { name: "Create source" }).should("be.visible");
    cy.assertDesktopFit();
    cy.screenshot("catalog-new-source-light", { capture: "fullPage" });
  });

  it("supports a persistent, legible dark theme", () => {
    cy.visit(`/org/${organizationId}/catalog/new`);
    cy.findByRole("button", { name: "Switch to dark theme" }).click();
    cy.get("html").should("have.class", "dark");
    cy.window().its("localStorage.theme").should("equal", "dark");
    cy.get("body").should("have.css", "background-color", "rgb(11, 15, 20)");
    cy.assertDesktopFit();
    cy.screenshot("catalog-new-source-dark", { capture: "fullPage" });
    cy.reload();
    cy.get("html").should("have.class", "dark");
    cy.findByRole("button", { name: "Switch to light theme" }).should("be.visible");
  });
});
