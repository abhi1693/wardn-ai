import { BarChart3 } from "lucide-react";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getCurrentUser } from "@/lib/current-user";
import {
  type UsageSummaryResponse,
  UsageSummaryView,
} from "@/app/components/usage-summary-view";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { canManageModelPrices } from "../llm-pricing/data";

type OrganizationUsagePageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getOrganizationUsage(organizationId: string) {
  return backendJson<UsageSummaryResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/usage/summary`
  );
}

export default async function OrganizationUsagePage({ params }: OrganizationUsagePageProps) {
  const { organizationId } = await params;
  const [workspaceContext, currentUser] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCurrentUser(),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  const canViewUsage = canManageModelPrices(currentUser, organization.currentUserRole);
  const usage = canViewUsage ? await getOrganizationUsage(organization.id) : null;

  return (
    <AppShell
      active="usage"
      eyebrow="Organization"
      title="Usage"
      workspaceContext={workspaceContext}
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <BarChart3 className="size-4" />
        Organization usage by user, workspace, agent, and model
      </div>

      {!canViewUsage ? (
        <Card>
          <CardHeader>
            <CardTitle>Usage access required</CardTitle>
            <CardDescription>
              Organization usage is available to owners, admins, and superusers.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Open My Usage to view your own model and tool activity.
          </CardContent>
        </Card>
      ) : usage ? (
        <UsageSummaryView mode="organization" usage={usage} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Usage unavailable</CardTitle>
            <CardDescription>
              The usage summary could not be loaded for this organization.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </AppShell>
  );
}
