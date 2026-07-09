import { BarChart3 } from "lucide-react";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  type UsageSummaryResponse,
  UsageSummaryView,
} from "@/app/components/usage-summary-view";
import { getOrganization } from "@/app/organizations/data";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

import { canManageModelPrices, getCurrentUser } from "../llm-pricing/data";

type OrganizationUsagePageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getOrganizationUsage(organizationId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(`/api/v1/organizations/${encodeURIComponent(organizationId)}/usage/summary`),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as UsageSummaryResponse;
  } catch {
    return null;
  }
}

export default async function OrganizationUsagePage({ params }: OrganizationUsagePageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, currentUser] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getCurrentUser(),
  ]);

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
