import { Button } from "@/components/atoms/button";
import { Toaster } from "@/components/atoms/sonner";
import {
  MutationFeedbackOutlet,
  MutationFeedbackProvider,
} from "@/components/providers/mutation-feedback-provider";
import { apiRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

function MutationHarness({ method = "POST" }: { method?: "DELETE" | "POST" | "PUT" }) {
  return (
    <MutationFeedbackProvider>
      <Button
        onClick={() =>
          void apiRequest("/api/test-mutation?access_token=do-not-copy", { method }).catch(
            () => undefined
          )
        }
      >
        Run mutation
      </Button>
      <MutationFeedbackOutlet />
      <Toaster position="bottom-right" />
    </MutationFeedbackProvider>
  );
}

describe("mutation feedback", () => {
  it("shows immediate pending feedback and a success toast", () => {
    cy.intercept("POST", "/api/test-mutation*", {
      body: { ok: true },
      delay: 250,
      statusCode: 200,
    });
    cy.mount(<MutationHarness />);

    cy.findByRole("button", { name: "Run mutation" }).click();
    cy.findByText("Working...").should("be.visible");
    cy.findByText("Completed successfully.").should("be.visible");
  });

  it("shows an actionable request-ID error and safely retries PUT", () => {
    let attempts = 0;
    cy.intercept("PUT", "/api/test-mutation*", (request) => {
      attempts += 1;
      if (attempts === 1) {
        request.reply({
          body: { detail: "The service is temporarily unavailable." },
          headers: { "x-request-id": "req-feedback-123" },
          statusCode: 503,
        });
        return;
      }
      request.reply({ body: { ok: true }, statusCode: 200 });
    }).as("mutation");
    cy.window().then((window) => {
      cy.stub(window.navigator.clipboard, "writeText").as("writeDiagnostics");
    });
    cy.mount(<MutationHarness method="PUT" />);

    cy.findByRole("button", { name: "Run mutation" }).click();
    cy.wait("@mutation");
    cy.get("[data-mutation-feedback-outlet]").within(() => {
      cy.findByText("The service is temporarily unavailable.").should("be.visible");
      cy.findByText("Request ID: req-feedback-123").should("be.visible");
      cy.findByRole("button", { name: "Copy diagnostics" }).click();
      cy.findByRole("button", { name: "Retry" }).click();
    });

    cy.get("@writeDiagnostics").should("have.been.calledOnce");
    cy.get("@writeDiagnostics").then((stub) => {
      const diagnostics = (
        stub as unknown as { firstCall: { args: [string] } }
      ).firstCall.args[0];
      expect(diagnostics).to.include("Request ID: req-feedback-123");
      expect(diagnostics).to.include("Request: PUT /api/test-mutation");
      expect(diagnostics).not.to.include("access_token");
      expect(diagnostics).not.to.include("temporarily unavailable.\"}");
    });
    cy.wait("@mutation");
    cy.findByText("Changes saved.").should("be.visible");
    cy.get("[data-mutation-feedback-outlet]").should("not.exist");
  });

  it("does not offer automatic retry for a failed POST", () => {
    cy.intercept("POST", "/api/test-mutation*", {
      body: { detail: "Creation failed.", requestId: "req-from-body" },
      statusCode: 503,
    });
    cy.mount(<MutationHarness />);

    cy.findByRole("button", { name: "Run mutation" }).click();
    cy.get("[data-mutation-feedback-outlet]").within(() => {
      cy.findByText("Request ID: req-from-body").should("be.visible");
      cy.findByRole("button", { name: "Retry" }).should("not.exist");
      cy.findByRole("button", { name: "Copy diagnostics" }).should("be.visible");
    });
  });

  it("exposes request IDs directly on API errors", () => {
    const error = new ApiError(409, { detail: "Conflict", requestId: "req-direct" }, "Failed");
    expect(error.requestId).to.equal("req-direct");
    expect(error.isRetryable).to.equal(false);
  });
});
