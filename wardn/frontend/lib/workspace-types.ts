export const selectedOrganizationCookie = "wardn_selected_organization";
export const selectedWorkspaceCookie = "wardn_selected_workspace";

export type OrganizationOption = {
  id: string;
  name: string;
  slug: string;
  status: string;
  currentUserRole: string;
};

export type WorkspaceOption = {
  id: string;
  organizationId: string;
  name: string;
  slug: string;
  status: string;
  currentUserRole: string;
};

export type WorkspaceContext = {
  organizations: OrganizationOption[];
  workspaces: WorkspaceOption[];
  selectedOrganization: OrganizationOption | null;
  selectedWorkspace: WorkspaceOption | null;
};
