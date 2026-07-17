import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getCurrentUser } from "@/lib/current-user";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getLlmCredentials } from "../../llm-credentials/data";
import { canManageModelPrices } from "../data";
import { ModelPriceForm } from "../model-price-form";

type NewModelPricePageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewModelPricePage({ params }: NewModelPricePageProps) {
  const { organizationId } = await params;
  const [workspaceContext, currentUser, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCurrentUser(),
    getLlmCredentials(organizationId),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization || !canManageModelPrices(currentUser, organization.currentUserRole)) {
    notFound();
  }

  return (
    <AppShell
      active="llm-pricing"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/llm-pricing`}>
            <ArrowLeft className="size-4" />
            Pricing
          </Link>
        </Button>
      }
      eyebrow="LLM Pricing"
      title="New Price"
      workspaceContext={workspaceContext}
    >
      <ModelPriceForm
        credentials={credentials}
        mode="create"
        organizationId={organization.id}
      />
    </AppShell>
  );
}
