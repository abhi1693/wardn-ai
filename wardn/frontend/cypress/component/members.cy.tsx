import { MembersClient } from "@/app/organizations/members-client";
import type { InvitationRead, MemberListResponse } from "@/lib/api/generated/model";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

function routerContext() {
  return {
    back: cy.stub(),
    forward: cy.stub(),
    prefetch: cy.stub(),
    push: cy.stub(),
    refresh: cy.stub(),
    replace: cy.stub(),
  };
}

const memberList: MemberListResponse = {
  canManage: true,
  canManageOwners: true,
  currentUserId: "user-owner",
  members: [
    {
      accessSource: "organization",
      createdAt: "2026-08-01T10:00:00Z",
      displayName: "Olivia Owner",
      email: "owner@example.com",
      firstName: "Olivia",
      lastName: "Owner",
      membershipId: "membership-owner",
      organizationRole: "owner",
      role: "owner",
      userId: "user-owner",
    },
  ],
};

function invitation(overrides: Partial<InvitationRead> = {}): InvitationRead {
  return {
    acceptedAt: null,
    acceptedById: null,
    createdAt: "2026-08-11T10:00:00Z",
    email: "member@example.com",
    expiresAt: "2026-08-18T10:00:00Z",
    id: "invitation-1",
    invitedById: "user-owner",
    organizationId: "organization-1",
    role: "member",
    scopeType: "organization",
    status: "pending",
    updatedAt: "2026-08-11T10:00:00Z",
    workspaceId: null,
    ...overrides,
  };
}

describe("membership management", () => {
  it("creates a manual invitation and exposes its one-time link", () => {
    cy.intercept("POST", "/api/v1/organizations/organization-1/invitations", {
      body: {
        invitation: invitation(),
        token: "one-time-invitation-token",
      },
      statusCode: 201,
    }).as("createInvitation");

    cy.mount(
      <AppRouterContext.Provider value={routerContext()}>
        <MembersClient
          initialInvitations={[]}
          memberList={memberList}
          organizationId="organization-1"
          scopeName="Acme"
          scopeType="organization"
        />
      </AppRouterContext.Provider>
    );

    cy.findByLabelText("Email").type("member@example.com");
    cy.findByRole("button", { name: "Create invite" }).click();

    cy.wait("@createInvitation")
      .its("request.body")
      .should("deep.equal", { email: "member@example.com", role: "member" });
    cy.findByText("Invitation created").should("be.visible");
    cy.findByLabelText("Invitation link")
      .should("be.visible")
      .and("have.value", `${window.location.origin}/invitations/one-time-invitation-token`);
    cy.findByText("member@example.com").should("be.visible");
    cy.findByText("Pending").should("be.visible");
  });

  it("renders inherited organization access as read-only in a workspace", () => {
    cy.mount(
      <AppRouterContext.Provider value={routerContext()}>
        <MembersClient
          initialInvitations={[]}
          memberList={{
            ...memberList,
            canManageOwners: false,
            members: [
              {
                ...memberList.members[0],
                membershipId: null,
                role: "admin",
              },
            ],
          }}
          organizationId="organization-1"
          scopeName="Production"
          scopeType="workspace"
          workspaceId="workspace-1"
        />
      </AppRouterContext.Provider>
    );

    cy.findByText("Organization owner").should("be.visible");
    cy.findByRole("cell", { name: "Admin" }).should("be.visible");
    cy.findByLabelText("Role for owner@example.com").should("not.exist");
    cy.findByLabelText("Remove owner@example.com").should("not.exist");
  });
});
