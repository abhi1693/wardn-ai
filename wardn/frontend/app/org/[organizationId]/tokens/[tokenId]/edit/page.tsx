import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type { UserAPITokenListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { EditTokenClient } from "./edit-token-client";

type EditOrganizationTokenPageProps = {
  params: Promise<{ organizationId: string; tokenId: string }>;
};

async function getApiTokens() {
  const payload = await backendJson<UserAPITokenListResponse>("/api/v1/auth/api-tokens");
  return payload.tokens;
}

export default async function EditOrganizationTokenPage({
  params,
}: EditOrganizationTokenPageProps) {
  const { organizationId, tokenId } = await params;
  const [workspaceContext, tokens] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getApiTokens(),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces;
  const token = tokens.find((entry) => entry.id === tokenId);

  if (!organization || !token) {
    notFound();
  }

  return (
    <AppShell
      active="agent-tokens"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/tokens`}>
            <ArrowLeft className="size-4" />
            Tokens
          </Link>
        </Button>
      }
      eyebrow="Agent Tokens"
      title="Edit Token"
      workspaceContext={workspaceContext}
    >
      <EditTokenClient organization={organization} token={token} workspaces={workspaces} />
    </AppShell>
  );
}
