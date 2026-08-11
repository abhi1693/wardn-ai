import { notFound } from "next/navigation";

import { MembersClient } from "@/app/organizations/members-client";
import { AppShell } from "@/components/templates/app-shell";
import type { InvitationListResponse, MemberListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

import { getWorkspaceContext } from "../../../../data";

type WorkspaceMembersPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceMembersPage({ params }: WorkspaceMembersPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;
  if (!organization || !workspace) {
    notFound();
  }

  const basePath = `/api/v1/organizations/${encodeURIComponent(
    organization.id
  )}/workspaces/${encodeURIComponent(workspace.id)}`;
  const memberList = await backendJson<MemberListResponse>(`${basePath}/members`);
  const invitations = memberList.canManage
    ? await backendJson<InvitationListResponse>(`${basePath}/invitations`)
    : { invitations: [] };

  return (
    <AppShell
      active="workspace-members"
      eyebrow="Workspace"
      title="Members"
      workspaceContext={workspaceContext}
    >
      <MembersClient
        initialInvitations={invitations.invitations}
        memberList={memberList}
        organizationId={organization.id}
        scopeName={workspace.name}
        scopeType="workspace"
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
