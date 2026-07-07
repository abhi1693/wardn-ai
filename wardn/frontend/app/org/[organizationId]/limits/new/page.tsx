import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getCurrentUser } from "../data";
import { LimitForm } from "../limit-form";

type NewLimitPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewLimitPage({ params }: NewLimitPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, currentUser] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getCurrentUser(),
  ]);

  if (!organization || !currentUser?.is_superuser) {
    notFound();
  }

  const workspaces = await getWorkspaces(organization.id);

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
      title="New Limit"
      workspaceContext={workspaceContext}
    >
      <LimitForm
        mode="create"
        organizationId={organization.id}
        organizations={[organization]}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
