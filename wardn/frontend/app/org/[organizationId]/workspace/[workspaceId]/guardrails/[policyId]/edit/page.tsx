import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import {
  getGuardrailPolicyRecords,
  getGuardrailWorkspaceOptions,
} from "../../data";
import { GuardrailForm } from "../../guardrail-form";

type EditGuardrailPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; policyId: string }>;
};

export default async function EditGuardrailPage({ params }: EditGuardrailPageProps) {
  const { organizationId, workspaceId, policyId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  const [records, options] = await Promise.all([
    getGuardrailPolicyRecords(organization.id, workspace.id),
    getGuardrailWorkspaceOptions(organization.id, workspace.id),
  ]);
  const record = records.find((item) => item.policy.id === policyId);

  if (!record) {
    notFound();
  }
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
      title="Edit Policy"
      workspaceContext={workspaceContext}
    >
      <GuardrailForm
        basePath={basePath}
        organization={organization}
        policy={record.policy}
        servers={options.servers}
        tools={options.tools}
        workspace={workspace}
      />
    </AppShell>
  );
}
