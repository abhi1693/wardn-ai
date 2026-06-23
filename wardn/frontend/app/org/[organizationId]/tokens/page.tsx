import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import type { UserAPITokenListResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

import { AgentTokensClient } from "./tokens-client";

type OrganizationTokensPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getApiTokens() {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath("/api/v1/auth/api-tokens"), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as UserAPITokenListResponse;
    return payload.tokens;
  } catch {
    return [];
  }
}

export default async function OrganizationTokensPage({ params }: OrganizationTokensPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, tokens] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getApiTokens(),
  ]);

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
