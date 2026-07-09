import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import {
  canManageModelPrices,
  getCurrentUser,
  getModelPriceById,
  getModelPrices,
} from "../../data";
import { ModelPriceForm } from "../../model-price-form";

type EditModelPricePageProps = {
  params: Promise<{ organizationId: string; priceId: string }>;
};

export default async function EditModelPricePage({ params }: EditModelPricePageProps) {
  const { organizationId, priceId } = await params;
  const [workspaceContext, organization, currentUser, prices] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getCurrentUser(),
    getModelPrices(organizationId),
  ]);

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
      <ModelPriceForm initialPrice={price} mode="edit" organizationId={organization.id} />
    </AppShell>
  );
}

