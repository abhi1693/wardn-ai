import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { getCurrentUser } from "@/lib/current-user";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getLlmCredentials } from "../../../llm-credentials/data";
import {
  canManageModelPrices,
  getModelPriceById,
  getModelPrices,
} from "../../data";
import { ModelPriceForm } from "../../model-price-form";

type EditModelPricePageProps = {
  params: Promise<{ organizationId: string; priceId: string }>;
};

export default async function EditModelPricePage({ params }: EditModelPricePageProps) {
  const { organizationId, priceId } = await params;
  const [workspaceContext, currentUser, prices, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCurrentUser(),
    getModelPrices(organizationId),
    getLlmCredentials(organizationId),
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
      title="Edit Price"
      workspaceContext={workspaceContext}
    >
      <ModelPriceForm
        credentials={credentials}
        initialPrice={price}
        mode="edit"
        organizationId={organization.id}
      />
    </AppShell>
  );
}
