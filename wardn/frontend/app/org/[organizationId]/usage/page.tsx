import { BarChart3, UserRound } from "lucide-react";
import Link from "next/link";
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
import { Button } from "@/components/ui/button";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { canManageModelPrices } from "../llm-pricing/data";

type OrganizationUsagePageProps = {
  params: Promise<{ organizationId: string }>;
  searchParams: Promise<{ scope?: string }>;
};

type UsageScope = "organization" | "me";

async function getOrganizationUsage(organizationId: string) {
  return backendJson<UsageSummaryResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/usage/summary`
  );
}

async function getMyUsage() {
  return backendJson<UsageSummaryResponse>("/api/v1/me/usage");
}

function usageScope(value: string | undefined, canViewOrganizationUsage: boolean): UsageScope {
  if (value === "organization") {
    return "organization";
  }
  if (value === "me") {
    return "me";
  }
  return canViewOrganizationUsage ? "organization" : "me";
}

function usageHref(organizationId: string, scope: UsageScope) {
  return `/org/${encodeURIComponent(organizationId)}/usage?scope=${scope}`;
}

export default async function OrganizationUsagePage({
  params,
  searchParams,
}: OrganizationUsagePageProps) {
  const { organizationId } = await params;
  const { scope } = await searchParams;
  const [workspaceContext, currentUser] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCurrentUser(),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  const canViewUsage = canManageModelPrices(currentUser, organization.currentUserRole);
  const selectedScope = usageScope(scope, canViewUsage);
  const usage =
    selectedScope === "organization" && canViewUsage
      ? await getOrganizationUsage(organization.id)
      : selectedScope === "me"
        ? await getMyUsage()
        : null;
  const isOrganizationScope = selectedScope === "organization";

  return (
    <AppShell
      active="usage"
      eyebrow="Organization"
      title="Usage"
      workspaceContext={workspaceContext}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {isOrganizationScope ? (
            <BarChart3 className="size-4" />
          ) : (
            <UserRound className="size-4" />
          )}
          {isOrganizationScope
            ? "Organization usage by user, workspace, agent, and model"
            : "Your attributed model requests, tokens, cost, and tool calls"}
        </div>
        <div
          aria-label="Usage scope"
          className="flex rounded-md border border-border bg-card p-1"
          role="tablist"
        >
          <Button asChild size="sm" variant={isOrganizationScope ? "default" : "ghost"}>
            <Link
              aria-selected={isOrganizationScope}
              href={usageHref(organization.id, "organization")}
              role="tab"
            >
              Organization
            </Link>
          </Button>
          <Button asChild size="sm" variant={!isOrganizationScope ? "default" : "ghost"}>
            <Link
              aria-selected={!isOrganizationScope}
              href={usageHref(organization.id, "me")}
              role="tab"
            >
              My usage
            </Link>
          </Button>
        </div>
      </div>

      {isOrganizationScope && !canViewUsage ? (
        <Card>
          <CardHeader>
            <CardTitle>Usage access required</CardTitle>
            <CardDescription>
              Organization usage is available to owners, admins, and superusers.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Switch to My usage to view your own model and tool activity.
          </CardContent>
        </Card>
      ) : usage ? (
        <UsageSummaryView mode={selectedScope} usage={usage} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Usage unavailable</CardTitle>
            <CardDescription>
              The usage summary could not be loaded.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </AppShell>
  );
}
