import { Activity, BookOpen, Boxes, Building2 } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import type { MCPCatalogSourceListResponse } from "@/app/catalog/catalog-source-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { backendJson } from "@/lib/api/server";
import {
  getWorkspaceContext,
  type WorkspaceContext,
} from "@/lib/workspace-context";

type OrganizationDashboardPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getCatalogSourceCount(context: WorkspaceContext) {
  const organizationId = context.selectedOrganization?.id;
  if (!organizationId) {
    return 0;
  }

  const payload = await backendJson<MCPCatalogSourceListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/mcp/catalog/sources`
  );
  return payload.sources.length;
}

export default async function OrganizationDashboardPage({
  params,
}: OrganizationDashboardPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces;

  if (!organization) {
    notFound();
  }

  const catalogSourceCount = await getCatalogSourceCount(workspaceContext);
  const activeWorkspaces = workspaces.filter((workspace) => workspace.status === "active").length;
  const overviewCards = [
    {
      label: "Organization",
      value: organization.status,
      detail: organization.slug,
      icon: Building2,
    },
    {
      label: "Workspaces",
      value: workspaces.length.toString(),
      detail: `${activeWorkspaces} active`,
      icon: Boxes,
    },
    {
      label: "Catalog sources",
      value: catalogSourceCount.toString(),
      detail: "Upstream URLs",
      icon: BookOpen,
    },
  ];

  return (
    <AppShell
      active="org-dashboard"
      eyebrow="Organization"
      title="Dashboard"
      workspaceContext={workspaceContext}
    >
      <section className="grid gap-4 md:grid-cols-3">
        {overviewCards.map((card) => {
          const Icon = card.icon;

          return (
            <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none" key={card.label}>
              <CardContent className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-xs font-semibold uppercase leading-4 tracking-[0.08em] text-[var(--on-surface-variant)]">
                      {card.label}
                    </div>
                    <div className="mt-3 text-3xl font-bold leading-9 text-[var(--on-surface)]">
                      {card.value}
                    </div>
                    <div className="mt-1 text-sm leading-5 text-[var(--on-surface-variant)]">
                      {card.detail}
                    </div>
                  </div>
                  <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container-highest)] text-[var(--on-surface-variant)]">
                    <Icon className="size-5" />
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <Card className="rounded-xl border-[var(--outline-variant)] bg-white shadow-none">
        <CardHeader>
          <div className="flex items-start justify-between gap-4 max-md:flex-col">
            <div>
              <CardTitle>Organization overview</CardTitle>
              <p className="mt-1 text-sm leading-5 text-[var(--on-surface-variant)]">
                A central view for org-wide activity, health, and runtime adoption.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button asChild size="sm" variant="outline">
                <Link href={`/org/${encodeURIComponent(organization.id)}/workspaces`}>
                  View workspaces
                </Link>
              </Button>
              <Button asChild size="sm">
                <Link href={`/org/${encodeURIComponent(organization.id)}/catalog`}>
                  View catalog
                </Link>
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-[280px_1fr]">
          <div className="rounded-lg border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-4">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                <Activity className="size-4" />
              </div>
              <div>
                <div className="text-sm font-semibold leading-5 text-[var(--on-surface)]">
                  Overview foundation
                </div>
                <div className="text-xs leading-4 text-[var(--on-surface-variant)]">
                  Ready for org metrics
                </div>
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-dashed border-[var(--outline-variant)] bg-[var(--surface)] p-4 text-sm leading-5 text-[var(--on-surface-variant)]">
            This page is the default organization landing area. We can add charts, recent
            workspace activity, server adoption, and operational alerts here as those data
            sources are finalized.
          </div>
        </CardContent>
      </Card>
    </AppShell>
  );
}
