import { notFound } from "next/navigation";
import {
  Activity,
  Bot,
  Gauge,
  Settings,
} from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";

import { getWorkspaceContext } from "../../../../data";
import { WorkspaceForm } from "../../../../workspace-form";

type WorkspaceSettingsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceSettingsPage({ params }: WorkspaceSettingsPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;
  if (!organization || !workspace) {
    notFound();
  }

  const workspaceBasePath = `/org/${encodeURIComponent(
    organization.id
  )}/workspace/${encodeURIComponent(workspace.id)}`;
  const adminLinks = [
    {
      description: "Configure named agents, model selection, instructions, and assigned tools.",
      href: `${workspaceBasePath}/agents`,
      icon: Bot,
      title: "Advanced Agents",
    },
    {
      description: "Inspect runtime sessions and manually stop unhealthy execution containers.",
      href: `${workspaceBasePath}/runtime`,
      icon: Activity,
      title: "Runtime Sessions",
    },
    {
      description: "Review raw MCP and LLM usage tables for deeper debugging.",
      href: `${workspaceBasePath}/observability`,
      icon: Gauge,
      title: "Observability",
    },
    {
      description: "Manage organization-wide credentials, tokens, limits, and secret storage.",
      href: `/organizations/${encodeURIComponent(organization.id)}/settings`,
      icon: Settings,
      title: "Organization Admin",
    },
  ];

  return (
    <AppShell
      active="workspace-settings"
      eyebrow="Workspace"
      title="Settings"
      workspaceContext={workspaceContext}
    >
      <div className="space-y-6">
        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {adminLinks.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] transition-colors hover:border-ring/40 hover:bg-muted/30"
                href={item.href}
                key={item.title}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold">{item.title}</div>
                  <Icon className="size-4 text-muted-foreground" />
                </div>
                <p className="mt-2 text-sm leading-5 text-muted-foreground">
                  {item.description}
                </p>
              </Link>
            );
          })}
        </section>

        <section className="space-y-3">
          <div>
            <h2 className="text-base font-semibold">Workspace Profile</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Edit the workspace name, description, and lifecycle status.
            </p>
          </div>
          <WorkspaceForm
            initialWorkspace={workspace}
            mode="edit"
            organizationId={organization.id}
          />
        </section>
      </div>
    </AppShell>
  );
}
