import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspace } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getGuardrailWorkspaceOptions } from "../data";
import { GuardrailForm } from "../guardrail-form";

type NewGuardrailPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function NewGuardrailPage({ params }: NewGuardrailPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, organization, workspace] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
    getWorkspace(organizationId, workspaceId),
  ]);

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
            Guardrails
          </Link>
        </Button>
      }
      eyebrow="Guardrails"
      title="Create Policy"
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
