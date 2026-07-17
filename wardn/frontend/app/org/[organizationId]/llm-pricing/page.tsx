import { BadgeDollarSign, Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getCurrentUser } from "@/lib/current-user";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { canManageModelPrices, getModelPrices } from "./data";
import { ModelPricingClient } from "./model-pricing-client";

type ModelPricingPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function ModelPricingPage({ params }: ModelPricingPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, currentUser, prices] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCurrentUser(),
    getModelPrices(organizationId),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  const canManage = canManageModelPrices(currentUser, organization.currentUserRole);

  return (
    <AppShell
      active="llm-pricing"
      actions={
        canManage ? (
          <Button asChild size="sm">
            <Link href={`/org/${organization.id}/llm-pricing/new`}>
              <Plus className="size-4" />
              New price
            </Link>
          </Button>
        ) : undefined
      }
      eyebrow="Organization"
      title="LLM Pricing"
      workspaceContext={workspaceContext}
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <BadgeDollarSign className="size-4" />
        {prices.length} configured model prices
      </div>
      <ModelPricingClient
        canManage={canManage}
        initialPrices={prices}
        organizationId={organization.id}
      />
    </AppShell>
  );
}
