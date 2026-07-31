import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import {
  getGuardrailPolicyRecords,
  getWorkspaceGuardrailSettings,
  getGuardrailWorkspaceOptions,
} from "./data";
import { GuardrailsClient } from "./guardrails-client";

type GuardrailsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function GuardrailsPage({ params }: GuardrailsPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  const [policies, settings, options] = await Promise.all([
    getGuardrailPolicyRecords(organization.id, workspace.id),
    getWorkspaceGuardrailSettings(organization.id, workspace.id),
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
            New rule
          </Link>
        </Button>
      }
      eyebrow="Workspace"
      title="Access Rules"
      workspaceContext={workspaceContext}
    >
      <GuardrailsClient
        basePath={basePath}
        initialSettings={settings}
        organizationId={organization.id}
        policies={policies}
        tools={options.tools}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
