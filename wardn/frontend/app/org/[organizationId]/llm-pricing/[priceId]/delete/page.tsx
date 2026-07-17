import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { getCurrentUser } from "@/lib/current-user";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { DeleteModelPriceClient } from "../../delete-model-price-client";
import {
  canManageModelPrices,
  getModelPriceById,
  getModelPrices,
} from "../../data";

type DeleteModelPricePageProps = {
  params: Promise<{ organizationId: string; priceId: string }>;
};

export default async function DeleteModelPricePage({
  params,
}: DeleteModelPricePageProps) {
  const { organizationId, priceId } = await params;
  const [workspaceContext, currentUser, prices] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCurrentUser(),
    getModelPrices(organizationId),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization || !canManageModelPrices(currentUser, organization.currentUserRole)) {
    notFound();
  }

  const price = getModelPriceById(prices, priceId);
  if (!price) {
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
      title="Delete Price"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-2xl">
        <DeleteModelPriceClient organizationId={organization.id} price={price} />
      </div>
    </AppShell>
  );
}
