import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";

export const selectedOrganizationCookie = "wardn_selected_organization";
export const selectedWorkspaceCookie = "wardn_selected_workspace";

export type OrganizationOption = OrganizationRead;

export type WorkspaceOption = WorkspaceRead;

export type WorkspaceContext = {
  organizations: OrganizationOption[];
  workspaces: WorkspaceOption[];
  selectedOrganization: OrganizationOption | null;
  selectedWorkspace: WorkspaceOption | null;
};
