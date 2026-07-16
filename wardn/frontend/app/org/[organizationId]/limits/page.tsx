import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getCurrentUser, getLimits, limitBelongsToOrganization } from "./data";
import { LimitsClient } from "./limits-client";

type LimitsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function LimitsPage({ params }: LimitsPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, currentUser, limits] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getCurrentUser(),
    getLimits(),
  ]);

  if (!organization) {
    notFound();
  }

  const workspaces = await getWorkspaces(organization.id);
  const scopedLimits = limits.filter((limit) =>
    limitBelongsToOrganization(limit, organization.id, workspaces)
  );

  return (
    <AppShell
      active="limits"
      actions={
        currentUser?.isSuperuser ? (
          <Button asChild size="sm">
            <Link href={`/org/${organization.id}/limits/new`}>
              <Plus className="size-4" />
              New limit
            </Link>
          </Button>
        ) : undefined
      }
      eyebrow="Organization"
      title="Limits"
      workspaceContext={workspaceContext}
    >
      <LimitsClient
        currentUser={currentUser}
        initialLimits={scopedLimits}
        organizationId={organization.id}
        organizations={[organization]}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
