"use client";

import { useRouter } from "next/navigation";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
  type WorkspaceContext,
} from "@/lib/workspace-types";

type WorkspaceSelectorProps = {
  context: WorkspaceContext;
};

function setSelectionCookie(name: string, value: string) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=31536000; samesite=lax`;
}

export function WorkspaceSelector({ context }: WorkspaceSelectorProps) {
  const router = useRouter();
  const selectedWorkspaceId = context.selectedWorkspace?.id ?? "";
  const organizationById = new Map(
    context.organizations.map((organization) => [organization.id, organization])
  );
  const selectedOrganization = context.selectedWorkspace
    ? organizationById.get(context.selectedWorkspace.organizationId)
    : context.selectedOrganization;
  const workspacesByOrganization = context.organizations
    .map((organization) => ({
      organization,
      workspaces: context.workspaces.filter(
        (workspace) => workspace.organizationId === organization.id
      ),
    }))
    .filter((group) => group.workspaces.length > 0);
  const hasWorkspaces = workspacesByOrganization.length > 0;

  if (context.organizations.length === 0) {
    return null;
  }

  return (
    <Select
      disabled={!hasWorkspaces}
      onValueChange={(workspaceId) => {
        const workspace = context.workspaces.find((item) => item.id === workspaceId);
        if (!workspace) {
          return;
        }
        setSelectionCookie(selectedOrganizationCookie, workspace.organizationId);
        setSelectionCookie(selectedWorkspaceCookie, workspace.id);
        router.push(
          `/org/${encodeURIComponent(workspace.organizationId)}/workspace/${encodeURIComponent(
            workspace.id
          )}/dashboard`
        );
        router.refresh();
      }}
      value={selectedWorkspaceId}
    >
      <SelectTrigger
        aria-label="Workspace context"
        className="h-auto min-h-11 w-full items-center border-slate-700 bg-sidebar-accent px-2.5 py-2 text-left text-slate-200 shadow-none hover:bg-slate-800 focus-visible:border-sky-400 [&>svg]:shrink-0 [&>svg]:text-slate-400"
      >
        <div className="min-w-0">
          <div className="truncate text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
            {selectedOrganization?.name ?? "Organization"}
          </div>
          <div className="truncate text-sm font-semibold leading-5 text-white">
            {context.selectedWorkspace?.name ?? "No workspace"}
          </div>
        </div>
      </SelectTrigger>
      <SelectContent className="w-[var(--radix-select-trigger-width)] min-w-64">
        {!hasWorkspaces ? (
          <SelectItem disabled value="empty">
            No workspaces
          </SelectItem>
        ) : null}
        {workspacesByOrganization.map(({ organization, workspaces }) => (
          <div key={organization.id}>
            <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-normal text-muted-foreground">
              {organization.name}
            </div>
            {workspaces.map((workspace) => (
              <SelectItem
                className="py-2 pl-3"
                key={workspace.id}
                value={workspace.id}
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">{workspace.name}</div>
                  <div className="truncate text-xs text-muted-foreground">{workspace.slug}</div>
                </div>
              </SelectItem>
            ))}
          </div>
        ))}
      </SelectContent>
    </Select>
  );
}
