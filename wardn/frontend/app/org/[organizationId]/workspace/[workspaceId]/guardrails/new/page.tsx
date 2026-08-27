import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { Button } from "@/components/atoms/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getGuardrailWorkspaceOptions } from "../data";
import { GuardrailForm } from "../guardrail-form";

type NewGuardrailPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function NewGuardrailPage({ params }: NewGuardrailPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  const options = await getGuardrailWorkspaceOptions(organization.id, workspace.id);
  const basePath = `/org/${encodeURIComponent(organization.id)}/workspace/${encodeURIComponent(
    workspace.id
  )}/guardrails`;

  return (
    <AppShell
      active="workspace-guardrails"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={basePath}>
            <ArrowLeft className="size-4" />
            Access
          </Link>
        </Button>
      }
      eyebrow="Access Rules"
      title="New Access Rule"
      workspaceContext={workspaceContext}
    >
      <GuardrailForm
        basePath={basePath}
        organization={organization}
        servers={options.servers}
        tools={options.tools}
        workspace={workspace}
      />
    </AppShell>
  );
}
