import { InvitationClient } from "@/app/invitations/[token]/invitation-client";
import type { InvitationAcceptanceRead, InvitationPreview } from "@/lib/api/generated/model";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

function routerContext(replace = cy.stub().as("replace")) {
  return {
    back: cy.stub(),
    forward: cy.stub(),
    prefetch: cy.stub(),
    push: cy.stub(),
    refresh: cy.stub().as("refresh"),
    replace,
  };
}

function preview(overrides: Partial<InvitationPreview> = {}): InvitationPreview {
  return {
    authMode: "oidc",
    currentUserEmail: "member@example.com",
    email: "member@example.com",
    expiresAt: "2026-08-18T10:00:00Z",
    oidcProviderName: "Zitadel",
    organizationId: "organization-1",
    organizationName: "Acme",
    role: "admin",
    scopeType: "organization",
    workspaceId: null,
    workspaceName: null,
    ...overrides,
  };
}

const acceptance: InvitationAcceptanceRead = {
  organizationId: "organization-1",
  organizationName: "Acme",
  userId: "user-1",
  workspaceId: null,
  workspaceName: null,
};

describe("invitation acceptance", () => {
  it("automatically accepts after OIDC returns with the invited email", () => {
    cy.intercept("GET", "/api/v1/invitations/invitation-token", {
      body: preview(),
    }).as("previewInvitation");
    cy.intercept("POST", "/api/v1/invitations/invitation-token/accept", {
      body: acceptance,
    }).as("acceptInvitation");

    cy.mount(
      <AppRouterContext.Provider value={routerContext()}>
        <InvitationClient token="invitation-token" />
      </AppRouterContext.Provider>
    );

    cy.wait("@previewInvitation");
    cy.wait("@acceptInvitation");
    cy.get("@replace").should("have.been.calledWith", "/org/organization-1/dashboard");
    cy.get("@refresh").should("have.been.called");
  });
});
