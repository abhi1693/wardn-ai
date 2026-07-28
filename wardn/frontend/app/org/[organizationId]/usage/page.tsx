import { BarChart3, ListFilter, UserRound } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { canManageModelPrices } from "../llm-pricing/data";

type OrganizationUsagePageProps = {
  params: Promise<{ organizationId: string }>;
  searchParams: Promise<{
    breakdownLimit?: string | string[];
    endDate?: string | string[];
    scope?: string | string[];
    startDate?: string | string[];
  }>;
};

type UsageScope = "organization" | "me";

const DEFAULT_BREAKDOWN_LIMIT = 25;
const DEFAULT_USAGE_DAYS = 30;
const BREAKDOWN_LIMIT_OPTIONS = [10, 25, 50, 100] as const;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

type UsageFilters = {
  breakdownLimit: number;
  endDate: string;
  hasBreakdownLimit: boolean;
  hasEndDate: boolean;
  hasStartDate: boolean;
  startDate: string;
};

function firstSearchParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function isIsoDate(value: string | undefined): value is string {
  return typeof value === "string" && ISO_DATE_PATTERN.test(value);
}

function utcDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function addDays(value: string, days: number) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return utcDate(date);
}

function normalizeBreakdownLimit(value: string | undefined) {
  const parsed = Number(value);
  return BREAKDOWN_LIMIT_OPTIONS.some((option) => option === parsed)
    ? parsed
    : DEFAULT_BREAKDOWN_LIMIT;
}

function usageFilters(
  searchParams: Awaited<OrganizationUsagePageProps["searchParams"]>
): UsageFilters {
  const requestedStartDate = firstSearchParam(searchParams.startDate);
  const requestedEndDate = firstSearchParam(searchParams.endDate);
  const requestedBreakdownLimit = firstSearchParam(searchParams.breakdownLimit);
  const hasStartDate = isIsoDate(requestedStartDate);
  const hasEndDate = isIsoDate(requestedEndDate);
  const hasBreakdownLimit = typeof requestedBreakdownLimit === "string";
  const today = utcDate(new Date());
  const endDate = hasEndDate ? requestedEndDate : today;
  const startDate = hasStartDate
    ? requestedStartDate
    : addDays(endDate, -(DEFAULT_USAGE_DAYS - 1));

  return {
    breakdownLimit: normalizeBreakdownLimit(requestedBreakdownLimit),
    endDate,
    hasBreakdownLimit,
    hasEndDate,
    hasStartDate,
    startDate,
  };
}

function usageQuery(filters: UsageFilters) {
  const params = new URLSearchParams();
  if (filters.hasStartDate) {
    params.set("startDate", filters.startDate);
  }
  if (filters.hasEndDate) {
    params.set("endDate", filters.endDate);
  }
  if (filters.hasBreakdownLimit) {
    params.set("breakdownLimit", String(filters.breakdownLimit));
  }
  return params;
}

function appendUsageQuery(path: string, filters: UsageFilters) {
  const params = usageQuery(filters);
  return params.size > 0 ? `${path}?${params.toString()}` : path;
}

async function getOrganizationUsage(organizationId: string, filters: UsageFilters) {
  const path = `/api/v1/organizations/${encodeURIComponent(organizationId)}/usage/summary`;
  return backendJson<UsageSummaryResponse>(appendUsageQuery(path, filters));
}

async function getMyUsage(filters: UsageFilters) {
  return backendJson<UsageSummaryResponse>(appendUsageQuery("/api/v1/me/usage", filters));
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

function usageHref(organizationId: string, scope: UsageScope, filters?: UsageFilters) {
  const params = new URLSearchParams({ scope });
  if (filters) {
    for (const [key, value] of usageQuery(filters)) {
      params.set(key, value);
    }
  }
  return `/org/${encodeURIComponent(organizationId)}/usage?${params.toString()}`;
}

export default async function OrganizationUsagePage({
  params,
  searchParams,
}: OrganizationUsagePageProps) {
  const { organizationId } = await params;
  const resolvedSearchParams = await searchParams;
  const scope = firstSearchParam(resolvedSearchParams.scope);
  const filters = usageFilters(resolvedSearchParams);
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
      ? await getOrganizationUsage(organization.id, filters)
      : selectedScope === "me"
        ? await getMyUsage(filters)
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
              href={usageHref(organization.id, "organization", filters)}
              role="tab"
            >
              Organization
            </Link>
          </Button>
          <Button asChild size="sm" variant={!isOrganizationScope ? "default" : "ghost"}>
            <Link
              aria-selected={!isOrganizationScope}
              href={usageHref(organization.id, "me", filters)}
              role="tab"
            >
              My usage
            </Link>
          </Button>
        </div>
      </div>
      <form
        className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-card p-3"
        method="get"
      >
        <input name="scope" type="hidden" value={selectedScope} />
        <div className="grid min-w-36 flex-1 gap-1.5 sm:flex-initial">
          <Label htmlFor="usage-start-date">Start date</Label>
          <Input
            defaultValue={filters.startDate}
            id="usage-start-date"
            name="startDate"
            type="date"
          />
        </div>
        <div className="grid min-w-36 flex-1 gap-1.5 sm:flex-initial">
          <Label htmlFor="usage-end-date">End date</Label>
          <Input
            defaultValue={filters.endDate}
            id="usage-end-date"
            name="endDate"
            type="date"
          />
        </div>
        <div className="grid min-w-32 flex-1 gap-1.5 sm:flex-initial">
          <Label htmlFor="usage-breakdown-limit">Rows</Label>
          <select
            className="h-9 rounded-[var(--radius)] border border-input bg-card px-3 text-sm outline-none ring-offset-background focus-visible:border-ring focus-visible:ring-ring/15 focus-visible:ring-[3px]"
            defaultValue={String(filters.breakdownLimit)}
            id="usage-breakdown-limit"
            name="breakdownLimit"
          >
            {BREAKDOWN_LIMIT_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <Button className="min-w-24" size="sm" type="submit">
          <ListFilter className="size-4" />
          Apply
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link href={usageHref(organization.id, selectedScope)}>Reset</Link>
        </Button>
      </form>

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
