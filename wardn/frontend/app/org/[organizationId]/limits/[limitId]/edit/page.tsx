import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getCurrentUser, getLimits, limitBelongsToOrganization } from "../../data";
import { LimitForm } from "../../limit-form";

type EditLimitPageProps = {
  params: Promise<{ organizationId: string; limitId: string }>;
};

export default async function EditLimitPage({ params }: EditLimitPageProps) {
  const { organizationId, limitId } = await params;
  const [workspaceContext, organization, currentUser, limits] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getCurrentUser(),
    getLimits(),
  ]);

  if (!organization || !currentUser?.isSuperuser) {
    notFound();
  }

  const workspaces = await getWorkspaces(organization.id);
  const limit = limits.find(
    (entry) => entry.id === limitId && limitBelongsToOrganization(entry, organization.id, workspaces)
  );
  if (!limit) {
    notFound();
  }

  return (
    <AppShell
      active="limits"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/limits`}>
            <ArrowLeft className="size-4" />
            Limits
          </Link>
        </Button>
      }
      eyebrow="Limits"
      title="Edit Limit"
      workspaceContext={workspaceContext}
    >
      <LimitForm
        initialLimit={limit}
        mode="edit"
        organizationId={organization.id}
        organizations={[organization]}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
