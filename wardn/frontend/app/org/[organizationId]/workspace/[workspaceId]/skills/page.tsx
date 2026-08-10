import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import type { AgentSkillCatalogResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { SkillsClient } from "./skills-client";

type WorkspaceSkillsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

async function getSkillCatalog(organizationId: string, workspaceId: string) {
  return backendJson<AgentSkillCatalogResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/skills`
  );
}

export default async function WorkspaceSkillsPage({ params }: WorkspaceSkillsPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, catalog] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getSkillCatalog(organizationId, workspaceId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-skills"
      eyebrow="Workspace"
      title="Skill Marketplace"
      workspaceContext={workspaceContext}
    >
      <SkillsClient
        initialCatalog={catalog}
        organizationId={organization.id}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
