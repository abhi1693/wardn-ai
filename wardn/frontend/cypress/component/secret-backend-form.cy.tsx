import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

import { SecretBackendForm } from "@/app/organizations/secret-backend-form";
import type { SecretStoreRead } from "@/lib/api/generated/model";

const organizationId = "00000000-0000-0000-0000-000000000001";
const store: SecretStoreRead = {
  id: "00000000-0000-0000-0000-000000000002",
  organizationId,
  name: "Local OpenBao",
  provider: "openbao",
  config: { baseUrl: "http://openbao:8200", kvMount: "secret" },
  authConfig: { profile: "compose" },
  isActive: true,
  createdAt: "2026-09-07T00:00:00Z",
  updatedAt: "2026-09-07T00:00:00Z",
};

function mountForm(mode: "create" | "edit") {
  const router = {
    back: cy.stub(),
    forward: cy.stub(),
    refresh: cy.stub(),
    hmrRefresh: cy.stub(),
    // Keep the form mounted to simulate a slow route transition after saving.
    push: cy.stub().as("navigate"),
    replace: cy.stub(),
    prefetch: cy.stub(),
  };
  cy.mount(
    <AppRouterContext.Provider value={router}>
      <SecretBackendForm
        mode={mode}
        organizationId={organizationId}
        store={mode === "edit" ? store : undefined}
      />
    </AppRouterContext.Provider>
  );
  if (mode === "create") {
    cy.findByLabelText("Name").type("Local OpenBao");
    cy.findByLabelText("OpenBao URL").type("http://openbao:8200");
    cy.findByLabelText("Authentication profile").type("compose");
  } else {
    cy.findByLabelText("Name").type(" updated");
  }
}

function expectUnloadProtection(expected: boolean) {
  cy.window().should((window) => {
    const event = new window.Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented, "unsaved-changes protection").to.equal(expected);
  });
}

describe("secret backend save navigation", () => {
  for (const mode of ["create", "edit"] as const) {
    it(`clears unload protection after ${mode} succeeds, even while navigation is pending`, () => {
      cy.intercept(
        mode === "create" ? "POST" : "PATCH",
        `/api/v1/organizations/${organizationId}/secrets/stores${mode === "edit" ? `/${store.id}` : ""}`,
        { statusCode: mode === "create" ? 201 : 200, body: store }
      ).as("save");
      mountForm(mode);
      expectUnloadProtection(true);

      cy.findByRole("button", { name: mode === "create" ? "Create backend" : "Save backend" }).click();
      cy.wait("@save");
      cy.get("@navigate").should("have.been.calledOnceWith", `/org/${organizationId}/secret-backends`);
      expectUnloadProtection(false);

      // Edits made after that successful save must still be protected.
      cy.findByLabelText("Name").type(" another change");
      expectUnloadProtection(true);
    });
  }

  it("keeps edits protected when the save fails", () => {
    cy.intercept("POST", `/api/v1/organizations/${organizationId}/secrets/stores`, {
      statusCode: 503,
      body: { detail: "Secret backend could not be saved." },
    }).as("save");
    mountForm("create");
    cy.findByRole("button", { name: "Create backend" }).click();
    cy.wait("@save");
    cy.findByRole("alert").should("contain.text", "Secret backend could not be saved.");
    cy.get("@navigate").should("not.have.been.called");
    expectUnloadProtection(true);
  });
});
