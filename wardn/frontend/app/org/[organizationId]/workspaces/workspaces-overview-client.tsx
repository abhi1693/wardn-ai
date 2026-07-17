"use client";

import { ArrowRight, Boxes, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";
import { setSelectionCookie } from "@/lib/selection-cookies";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type WorkspacesOverviewClientProps = {
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

export function WorkspacesOverviewClient({
  organization,
  workspaces,
}: WorkspacesOverviewClientProps) {
  const router = useRouter();

  function openWorkspace(workspace: WorkspaceRead) {
    setSelectionCookie(selectedOrganizationCookie, workspace.organizationId);
    setSelectionCookie(selectedWorkspaceCookie, workspace.id);
    router.push(
      `/org/${encodeURIComponent(workspace.organizationId)}/workspace/${encodeURIComponent(
        workspace.id
      )}/chat`
    );
    router.refresh();
  }

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
        {workspaces.map((workspace) => (
          <button
            aria-label={`Open ${workspace.name}`}
            className="group relative min-h-32 overflow-hidden rounded-md border border-border bg-card text-left shadow-[var(--shadow-card)] transition-colors hover:border-ring/40 hover:bg-muted/30 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/15"
            key={workspace.id}
            onClick={() => openWorkspace(workspace)}
            type="button"
          >
            <div className="p-4">
              <div className="flex flex-col gap-2">
                <div className="mb-1 flex size-8 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                  <Boxes className="size-4" />
                </div>
                <h3 className="text-base font-semibold leading-6 text-foreground">
                  {workspace.name}
                </h3>
                <p className="break-all text-sm leading-5 text-muted-foreground">
                  {workspace.slug}
                </p>
                <div className="mt-2 border-t border-border pt-3">
                  <span className="inline-flex items-center gap-2 text-sm font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">
                    Open workspace
                    <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </div>
              </div>
            </div>
          </button>
        ))}

        <Link
          className="group flex min-h-32 flex-col items-center justify-center rounded-md border border-dashed border-border p-4 text-center transition-colors hover:border-ring/40 hover:bg-muted/40"
          href={`/organizations/${organization.id}/workspaces/new`}
        >
          <div className="mb-3 flex size-8 items-center justify-center rounded-md border border-border bg-muted">
            <Plus className="size-4 text-muted-foreground group-hover:text-foreground" />
          </div>
          <h3 className="mb-1 text-sm font-semibold leading-5 text-foreground">
            Create Workspace
          </h3>
          <p className="max-w-[220px] text-sm leading-5 text-muted-foreground">
            Isolate projects and environments with a new secure workspace.
          </p>
        </Link>
      </section>

      {workspaces.length === 0 ? (
        <section className="rounded-md border border-border bg-card p-6 text-center">
          <div className="mx-auto mb-4 flex size-10 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
            <ArrowRight className="size-5" />
          </div>
          <h3 className="text-xl font-semibold">No workspaces yet</h3>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
            Create the first workspace for {organization.name} to start installing and managing MCP
            servers.
          </p>
        </section>
      ) : null}
    </div>
  );
}
