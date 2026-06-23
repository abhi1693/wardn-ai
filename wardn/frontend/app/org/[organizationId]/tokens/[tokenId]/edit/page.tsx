import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import type { UserAPITokenListResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

import { EditTokenClient } from "./edit-token-client";

type EditOrganizationTokenPageProps = {
  params: Promise<{ organizationId: string; tokenId: string }>;
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

export default async function EditOrganizationTokenPage({
  params,
}: EditOrganizationTokenPageProps) {
  const { organizationId, tokenId } = await params;
  const [workspaceContext, organization, workspaces, tokens] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
    getApiTokens(),
  ]);
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
