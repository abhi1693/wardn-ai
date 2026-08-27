export {};

const organizationId = "org-1";
const workspaceId = "workspace-1";
const serverName = "io.github.acamolese/google-search-console-mcp";
const installPath = `/org/${organizationId}/workspace/${workspaceId}/install/new`;

function selectedServerPath() {
  return `${installPath}?serverName=${encodeURIComponent(serverName)}&version=1.0.0`;
}

describe("MCP install runtime selection", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
  });

  it("loads the supported server picker with Hub metadata", () => {
    cy.visit(installPath);
    cy.findByRole("heading", { name: "New Connection" }).should("be.visible");
    cy.get('img[src="https://skills.sh/badge/google-search-console.svg"]')
      .should("have.class", "object-contain");
    cy.findByRole("link", { name: "View in Hub" })
      .should(
        "have.attr",
        "href",
        "https://hub.wardnai.dev/servers/io.github.acamolese/google-search-console-mcp"
      )
      .and("have.attr", "target", "_blank");

    cy.backendRequests().then((requests) => {
      const listRequest = requests.find(
        (entry) =>
          entry.method === "GET" &&
          entry.path === `/api/v1/organizations/${organizationId}/mcp/registry/servers`
      );
      expect(listRequest?.query).to.deep.include({ limit: "12", version: "latest" });
    });
  });

  it("submits streamable HTTP as the default runtime", () => {
    cy.visit(selectedServerPath());
    cy.findByRole("combobox", { name: "Runtime" }).should("contain.text", "Streamable HTTP");
    cy.findByTestId("install-target-details").should("contain.text", "gsc.example.com");
    cy.findByRole("button", { name: "Create connection" }).click();
    cy.location("pathname").should("equal", `/org/${organizationId}/workspace/${workspaceId}/install`);

    cy.backendRequests().then((requests) => {
      const install = requests.find(
        (entry) =>
          entry.method === "PUT" &&
          entry.path.includes("/mcp/registry/installed-servers/")
      );
      expect(install?.body).to.deep.include({
        configName: "default",
        installTarget: "remote",
        version: "1.0.0",
      });
    });
  });

  it("shows package details and submits a switched runtime", () => {
    cy.visit(selectedServerPath());
    cy.findByRole("link", { name: serverName }).should(
      "have.attr",
      "href",
      "https://hub.wardnai.dev/servers/io.github.acamolese/google-search-console-mcp"
    );
    cy.findByTestId("install-target-details")
      .should("contain.text", "gsc.example.com")
      .and("contain.text", "Connection version: 1.0.0");

    cy.findByRole("combobox", { name: "Runtime" }).click();
    cy.findByRole("option", { name: /UVX .* google-search-console-mcp/ }).click();
    cy.findByRole("combobox", { name: "Runtime" }).should("contain.text", "UVX");
    cy.findByTestId("install-target-details")
      .should("contain.text", "google-search-console-mcp")
      .and("contain.text", "Package version: 1.0.0");
    cy.findByRole("button", { name: "Create connection" }).click();
    cy.location("pathname").should("equal", `/org/${organizationId}/workspace/${workspaceId}/install`);

    cy.backendRequests().then((requests) => {
      const install = requests.find((entry) => entry.method === "PUT");
      expect(install?.body).to.deep.include({ installTarget: "package:1", version: "1.0.0" });
    });
  });

  it("hides remote egress when the package has no remote endpoint", () => {
    cy.resetBackend({ packageRuntimeProvider: "kubernetes", serverRemotes: [] });
    cy.visit(selectedServerPath());
    cy.findByText("Runtime dependencies", { exact: true }).should("be.visible");
    cy.findByText("Kubernetes API", { exact: true }).should("be.visible");
    cy.findByText("Deny other egress", { exact: true }).should("be.visible");
    cy.findByText("Remote MCP endpoints", { exact: true }).should("not.exist");
    cy.findByRole("button", { name: "Create connection" }).click();

    cy.backendRequests().then((requests) => {
      const install = requests.find((entry) => entry.method === "PUT");
      expect(install?.body?.networkPolicy).to.deep.include({
        allowRemoteMcpEgress: false,
        allowRuntimeDependencyEgress: true,
        denyOtherEgress: true,
      });
    });
  });
});

describe("skill marketplace", () => {
  beforeEach(() => {
    cy.resetBackend();
    cy.login();
  });

  it("discovers, approves, and shows usage evidence", () => {
    cy.intercept("GET", "**/skills/search*").as("skillSearch");
    cy.visit(`/org/${organizationId}/workspace/${workspaceId}/skills`);
    cy.findByRole("heading", { name: "Skill Marketplace" }).should("be.visible");
    cy.findByText("Discover Hub Skills").should("be.visible");
    cy.findByLabelText("Search Wardn Hub skills").should("have.value", "").type("kubernetes ops");
    cy.findByRole("button", { name: "Search" }).click();
    cy.wait("@skillSearch").its("response.statusCode").should("equal", 200);
    cy.findByRole("button", { name: "Approve" }).click();
    cy.findByRole("tab", { name: /Workspace Library/ }).should(
      "have.attr",
      "aria-selected",
      "true"
    );
    cy.findByText(/hash-123/).should("be.visible");
    cy.findByText("Workspace agent", { exact: true }).should("be.visible");
    cy.findByRole("tab", { name: /Usage/ }).click();
    cy.findByText("Fetched owner/repo/kubernetes-ops with audit pass.").should("be.visible");
    cy.findAllByText("Approved").last().should("be.visible");

    cy.backendRequests().then((requests) => {
      const approval = requests.find(
        (entry) => entry.method === "POST" && entry.path.endsWith("/skills/library")
      );
      expect(approval?.body).to.deep.include({ skillId: "owner/repo/kubernetes-ops" });
    });
  });
});
