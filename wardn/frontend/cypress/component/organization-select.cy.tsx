import { OrganizationSelectClient } from "@/app/org/organization-select-client";
import type { OrganizationRead, PendingInvitationRead } from "@/lib/api/generated/model";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

function routerContext(push = cy.stub().as("push")) {
  return {
    back: cy.stub(),
    forward: cy.stub(),
    prefetch: cy.stub(),
    push,
    refresh: cy.stub().as("refresh"),
    replace: cy.stub(),
  };
}

const pendingInvitation: PendingInvitationRead = {
  expiresAt: "2026-08-18T10:00:00Z",
  id: "invitation-1",
  organizationId: "organization-1",
  organizationName: "Acme",
  role: "admin",
  scopeType: "organization",
  workspaceId: null,
  workspaceName: null,
};

const organization: OrganizationRead = {
  createdAt: "2026-08-11T10:00:00Z",
  currentUserRole: "owner",
  id: "organization-existing",
  name: "Existing",
  slug: "existing",
  status: "active",
  updatedAt: "2026-08-11T10:00:00Z",
};

describe("organization selection", () => {
  it("shows pending invitations and accepts them for the signed-in user", () => {
    cy.intercept("POST", "/api/v1/invitations/pending/invitation-1/accept", {
      body: {
        organizationId: "organization-1",
        organizationName: "Acme",
        userId: "user-1",
        workspaceId: null,
        workspaceName: null,
      },
    }).as("acceptInvitation");

    cy.mount(
      <AppRouterContext.Provider value={routerContext()}>
        <OrganizationSelectClient
          organizations={[organization]}
          pendingInvitations={[pendingInvitation]}
        />
      </AppRouterContext.Provider>
    );

    cy.findByRole("heading", { name: "Pending invitations" }).should("be.visible");
    cy.findByText("Acme").should("be.visible");
    cy.findByRole("button", { name: "Accept invitation" }).click();

    cy.wait("@acceptInvitation");
    cy.get("@push").should("have.been.calledWith", "/org/organization-1/dashboard");
    cy.get("@refresh").should("have.been.called");
  });
});
