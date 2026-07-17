import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type { UserAPITokenListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { AgentTokensClient } from "./tokens-client";

type OrganizationTokensPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getApiTokens() {
  const payload = await backendJson<UserAPITokenListResponse>("/api/v1/auth/api-tokens");
  return payload.tokens;
}

export default async function OrganizationTokensPage({ params }: OrganizationTokensPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, tokens] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getApiTokens(),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="agent-tokens"
      actions={
        <Button asChild size="sm">
          <Link href={`/org/${organization.id}/tokens/new`}>
            <Plus className="size-4" />
            New token
          </Link>
        </Button>
      }
      eyebrow="Organization"
      title="Agent Tokens"
      workspaceContext={workspaceContext}
    >
      <AgentTokensClient initialTokens={tokens} organization={organization} />
    </AppShell>
  );
}
