const organizationId = "org-1";
const workspaceId = "workspace-1";

export {};
const providerBasePath =
  `/org/${organizationId}/workspace/${workspaceId}/chat-providers`;
const scheduledTasksBasePath =
  `/org/${organizationId}/workspace/${workspaceId}/scheduled-tasks`;

function openAuthenticated(path: string) {
  cy.login();
  cy.visit(path);
}

function completeWhatsappProviderFields() {
  cy.findByLabelText(/Name/).clear();
  cy.findByLabelText(/Name/).type("Operations WhatsApp");
  cy.findByLabelText("WhatsApp gateway URL").clear();
  cy.findByLabelText("WhatsApp gateway URL").type("https://whatsapp.example.com");
}

describe("reliable feature forms", () => {
  beforeEach(() => {
    cy.resetBackend();
  });

  it("summarizes provider validation and focuses the first invalid field", () => {
    openAuthenticated(`${providerBasePath}/new`);
    cy.findByRole("heading", { name: "New Chat Provider" }).should("be.visible");
    cy.findByLabelText(/Name/).clear();
    cy.findByRole("button", { name: "Create provider" }).click();

    cy.findByText("Review the highlighted fields").should("be.visible");
    cy.findByRole("button", { name: /Name: Enter a provider name/ }).should("be.visible");
    cy.findByLabelText(/Name/).should("have.focus").and("have.attr", "aria-invalid", "true");
  });

  it("keeps API errors durable, prevents duplicate submit, and recovers on retry", () => {
    cy.resetBackend({ chatProviderConnections: [], chatProviderSaveStatus: 503 });
    openAuthenticated(`${providerBasePath}/new`);
    completeWhatsappProviderFields();
    cy.findByRole("button", { name: "Create provider" }).click();

    cy.findByRole("alert").should("contain.text", "provider connection could not be saved");
    cy.findByRole("button", { name: "Create provider" }).should("be.enabled");

    cy.resetBackend({ chatProviderConnections: [], chatProviderSaveDelayMs: 400 });
    cy.findByRole("button", { name: "Create provider" }).click();
    cy.findByRole("button", { name: "Create provider" }).should("be.disabled");
    cy.location("pathname").should("match", new RegExp(`${providerBasePath}/[^/]+/edit$`));
    cy.backendRequests().then((requests) => {
      expect(
        requests.filter(
          (request) => request.method === "POST" && request.path.endsWith("/chat-providers")
        )
      ).to.have.length(1);
    });
  });

  it("protects dirty provider changes before explicit navigation", () => {
    openAuthenticated(`${providerBasePath}/new`);
    cy.window().then((window) =>
      cy.stub(window, "confirm").onFirstCall().returns(false).onSecondCall().returns(true)
    );
    cy.findByLabelText(/Name/).clear();
    cy.findByLabelText(/Name/).type("Unsaved provider");

    cy.findByRole("link", { name: "Cancel" }).click();
    cy.location("pathname").should("equal", `${providerBasePath}/new`);
    cy.findByRole("link", { name: "Cancel" }).click();
    cy.location("pathname").should("equal", providerBasePath);
  });

  it("validates scheduled tasks, focuses errors, and submits after correction", () => {
    openAuthenticated(`${scheduledTasksBasePath}/new`);
    cy.findByRole("heading", { name: "New Scheduled Task" }).should("be.visible");
    cy.get("header").findByLabelText("Feature maturity: Alpha").should("be.visible");
    cy.findByRole("button", { name: "Review" }).click();
    cy.findByRole("button", { name: "Create" }).click();

    cy.findByText("Review the highlighted fields").should("be.visible");
    cy.findByLabelText("Task name").should("have.focus");
    cy.findByLabelText("Task name").type("Daily operations summary");
    cy.findByLabelText("Prompt").type("Summarize failed runtime operations and required action.");
    cy.findByRole("button", { name: "Review" }).click();
    cy.findByRole("button", { name: "Create" }).click();

    cy.location("pathname").should("equal", scheduledTasksBasePath);
    cy.findByRole("heading", { name: "Scheduled Tasks" }).should("be.visible");
    cy.backendRequests().then((requests) => {
      expect(
        requests.filter(
          (request) => request.method === "POST" && request.path.endsWith("/scheduled-tasks")
        )
      ).to.have.length(1);
    });
  });
});
