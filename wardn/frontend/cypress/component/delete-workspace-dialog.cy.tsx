import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

import { DeleteWorkspaceDialog } from "@/app/organizations/delete-workspace-dialog";
import { OrganizationWorkspacesList } from "@/components/organisms/organization-workspaces-list";
import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";

const organization: OrganizationRead = {
  createdAt: "2026-08-01T10:00:00Z",
  currentUserRole: "owner",
  id: "organization-1",
  name: "Default Organization",
  slug: "default",
  status: "active",
  updatedAt: "2026-08-27T10:00:00Z",
};

const workspace: WorkspaceRead = {
  createdAt: "2026-08-27T10:00:00Z",
  currentUserRole: "owner",
  description: "Temporary workspace",
  guardrailDefaultDeny: false,
  id: "workspace-1",
  name: "Test Workspace",
  organizationId: "organization-1",
  slug: "test",
  status: "active",
  updatedAt: "2026-08-27T10:00:00Z",
};

function routerContext() {
  return {
    back: cy.stub(),
    forward: cy.stub(),
    prefetch: cy.stub(),
    push: cy.stub().as("push"),
    refresh: cy.stub().as("refresh"),
    replace: cy.stub(),
  };
}

function mountDialog() {
  cy.mount(
    <AppRouterContext.Provider value={routerContext()}>
      <DeleteWorkspaceDialog organizationId="organization-1" workspace={workspace} />
    </AppRouterContext.Provider>
  );
}

describe("workspace deletion", () => {
  it("offers deletion on manageable cards but protects the default workspace", () => {
    const defaultWorkspace: WorkspaceRead = {
      ...workspace,
      id: "workspace-default",
      name: "Default Workspace",
      slug: "default",
    };
    cy.mount(
      <AppRouterContext.Provider value={routerContext()}>
        <OrganizationWorkspacesList
          organization={organization}
          workspaces={[defaultWorkspace, workspace]}
        />
      </AppRouterContext.Provider>
    );

    cy.findByRole("button", { name: "Delete Test Workspace workspace" }).should("be.visible");
    cy.findByRole("button", { name: "Delete Default Workspace workspace" }).should("not.exist");
  });

  it("requires the exact workspace name before deleting and clears stale selection", () => {
    cy.intercept("DELETE", "/api/v1/organizations/organization-1/workspaces/workspace-1", {
      statusCode: 204,
    }).as("deleteWorkspace");
    cy.setCookie("wardn_selected_workspace", workspace.id);
    mountDialog();

    cy.findByRole("button", { name: "Delete workspace" }).click();
    cy.findByRole("alertdialog").within(() => {
      cy.findByRole("button", { name: "Delete workspace" }).should("be.disabled");
      cy.findByLabelText(/Type Test Workspace to confirm/).type("test workspace");
      cy.findByRole("button", { name: "Delete workspace" }).should("be.disabled");
      cy.findByLabelText(/Type Test Workspace to confirm/).clear().type("Test Workspace");
      cy.findByRole("button", { name: "Delete workspace" }).should("be.enabled").click();
    });

    cy.wait("@deleteWorkspace");
    cy.get("@push").should("have.been.calledWith", "/org/organization-1/workspaces");
    cy.get("@refresh").should("have.been.calledOnce");
    cy.getCookie("wardn_selected_workspace").should("be.null");
  });

  it("keeps the dialog open and explains dependency conflicts", () => {
    cy.intercept("DELETE", "/api/v1/organizations/organization-1/workspaces/workspace-1", {
      body: { detail: "uninstall all MCP server configurations before deleting this workspace" },
      statusCode: 409,
    }).as("blockedDelete");
    mountDialog();

    cy.findByRole("button", { name: "Delete workspace" }).click();
    cy.findByLabelText(/Type Test Workspace to confirm/).type("Test Workspace");
    cy.findByRole("alertdialog")
      .findByRole("button", { name: "Delete workspace" })
      .click();

    cy.wait("@blockedDelete");
    cy.findByRole("alertdialog").should("be.visible");
    cy.findByRole("alert").should(
      "contain.text",
      "uninstall all MCP server configurations before deleting this workspace"
    );
  });
});
