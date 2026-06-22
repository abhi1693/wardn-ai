"use client";

import { ArrowRight, Boxes, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type WorkspacesOverviewClientProps = {
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

function setSelectionCookie(name: string, value: string) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=31536000; samesite=lax`;
}

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
      )}/dashboard`
    );
    router.refresh();
  }

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-5">
        {workspaces.map((workspace, index) => (
          <button
            aria-label={`Open ${workspace.name}`}
            className="group relative min-h-40 overflow-hidden rounded-xl border border-[var(--outline-variant)] bg-white text-left shadow-[var(--shadow-card)] transition-shadow hover:shadow-md focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/25"
            key={workspace.id}
            onClick={() => openWorkspace(workspace)}
            type="button"
          >
            <div className="p-5">
              <div className="flex flex-col gap-2">
                <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-[var(--on-surface-variant)]">
                  <Boxes className="size-5 transition-transform group-hover:scale-105" />
                </div>
                <h3 className="text-xl font-semibold leading-7 text-primary">
                  {index === 0 ? "Default Workspace" : workspace.name}
                </h3>
                <p className="break-all text-sm leading-5 text-[var(--on-surface-variant)]">
                  {workspace.slug}
                </p>
                <div className="mt-3 border-t border-[var(--outline-variant)] pt-3">
                  <span className="inline-flex items-center gap-2 text-sm font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
                    Open workspace
                    <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </div>
              </div>
            </div>
          </button>
        ))}

        <Link
          className="group flex min-h-40 flex-col items-center justify-center rounded-xl border-2 border-dashed border-[var(--outline-variant)] p-5 text-center transition-all hover:border-primary/30 hover:bg-[var(--surface-container-low)]"
          href={`/organizations/${organization.id}/workspaces/new`}
        >
          <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-[var(--surface-container-highest)] transition-all group-hover:scale-110 group-hover:bg-[var(--primary-fixed)]">
            <Plus className="size-6 text-[var(--on-surface-variant)] group-hover:text-primary" />
          </div>
          <h3 className="mb-1 text-lg font-semibold leading-6 text-[var(--on-surface)]">
            Create Workspace
          </h3>
          <p className="max-w-[220px] text-sm leading-5 text-[var(--on-surface-variant)]">
            Isolate projects and environments with a new secure workspace.
          </p>
        </Link>
      </section>

      {workspaces.length === 0 ? (
        <section className="rounded-xl border border-[var(--outline-variant)] bg-white p-6 text-center">
          <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-lg bg-[var(--surface-container)] text-[var(--on-surface-variant)]">
            <ArrowRight className="size-5" />
          </div>
          <h3 className="text-xl font-semibold">No workspaces yet</h3>
          <p className="mx-auto mt-2 max-w-md text-sm text-[var(--on-surface-variant)]">
            Create the first workspace for {organization.name} to start installing and managing MCP
            servers.
          </p>
        </section>
      ) : null}
    </div>
  );
}
