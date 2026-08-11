import { notFound } from "next/navigation";

import { MembersClient } from "@/app/organizations/members-client";
import { AppShell } from "@/components/templates/app-shell";
import type { InvitationListResponse, MemberListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

import { getWorkspaceContext } from "../../data";

type OrganizationMembersPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationMembersPage({ params }: OrganizationMembersPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  if (!organization) {
    notFound();
  }

  const memberList = await backendJson<MemberListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organization.id)}/members`
  );
  const invitations = memberList.canManage
    ? await backendJson<InvitationListResponse>(
        `/api/v1/organizations/${encodeURIComponent(organization.id)}/invitations`
      )
    : { invitations: [] };

  return (
    <AppShell
      active="organization-members"
      eyebrow="Organization"
      title="Members"
      workspaceContext={workspaceContext}
    >
      <MembersClient
        initialInvitations={invitations.invitations}
        memberList={memberList}
        organizationId={organization.id}
        scopeName={organization.name}
        scopeType="organization"
      />
    </AppShell>
  );
}
