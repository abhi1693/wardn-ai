import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspace } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import {
  getGuardrailPolicyRecords,
  getGuardrailWorkspaceOptions,
} from "./data";
import { GuardrailsClient } from "./guardrails-client";

type GuardrailsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function GuardrailsPage({ params }: GuardrailsPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, organization, workspace] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
    getWorkspace(organizationId, workspaceId),
  ]);

  if (!organization || !workspace) {
    notFound();
  }

  const [policies, options] = await Promise.all([
    getGuardrailPolicyRecords(organization.id, workspace.id),
    getGuardrailWorkspaceOptions(organization.id, workspace.id),
  ]);
  const basePath = `/org/${encodeURIComponent(organization.id)}/workspace/${encodeURIComponent(
    workspace.id
  )}/guardrails`;

  return (
    <AppShell
      active="workspace-guardrails"
      actions={
        <Button asChild size="sm">
          <Link href={`${basePath}/new`}>
            <Plus className="size-4" />
            New policy
          </Link>
        </Button>
      }
      eyebrow="Workspace"
      title="Guardrails"
      workspaceContext={workspaceContext}
    >
      <GuardrailsClient
        basePath={basePath}
        organizationId={organization.id}
        policies={policies}
        tools={options.tools}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
