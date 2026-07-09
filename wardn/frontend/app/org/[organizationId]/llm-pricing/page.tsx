import { BadgeDollarSign } from "lucide-react";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization } from "@/app/organizations/data";
import { Badge } from "@/components/ui/badge";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getCurrentUser, getModelPrices } from "./data";
import { ModelPricingClient } from "./model-pricing-client";

type ModelPricingPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function ModelPricingPage({ params }: ModelPricingPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, currentUser, prices] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getCurrentUser(),
    getModelPrices(organizationId),
  ]);

  if (!organization) {
    notFound();
  }

  const canManage =
    currentUser?.is_superuser ||
    organization.currentUserRole === "owner" ||
    organization.currentUserRole === "admin";

  return (
    <AppShell
      active="llm-pricing"
      actions={
        <Badge variant="outline">
          <BadgeDollarSign className="size-3.5" />
          {prices.length} models
        </Badge>
      }
      eyebrow="Organization"
      title="LLM Pricing"
      workspaceContext={workspaceContext}
    >
      <ModelPricingClient
        canManage={Boolean(canManage)}
        initialPrices={prices}
        organizationId={organization.id}
      />
    </AppShell>
  );
}

