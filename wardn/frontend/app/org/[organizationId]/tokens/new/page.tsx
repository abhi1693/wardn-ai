import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { CreateTokenClient } from "./create-token-client";

type NewOrganizationTokenPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewOrganizationTokenPage({
  params,
}: NewOrganizationTokenPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, workspaces] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
  ]);

  if (!organization) {
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
      title="Create Token"
      workspaceContext={workspaceContext}
    >
      <CreateTokenClient organization={organization} workspaces={workspaces} />
    </AppShell>
  );
}
