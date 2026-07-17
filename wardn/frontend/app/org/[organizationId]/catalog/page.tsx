import { Plus } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { CatalogSourcesClient } from "@/app/catalog/catalog-sources-client";
import type { MCPCatalogSourceListResponse } from "@/app/catalog/catalog-source-types";
import { Button } from "@/components/ui/button";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationCatalogPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getCatalogSources(organizationId: string) {
  const payload = await backendJson<MCPCatalogSourceListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/mcp/catalog/sources`
  );
  return payload.sources;
}

export default async function OrganizationCatalogPage({
  params,
}: OrganizationCatalogPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, sources] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCatalogSources(organizationId),
  ]);

  return (
    <AppShell
      active="catalog"
      actions={
        <Button asChild size="sm">
          <Link href={`/org/${encodeURIComponent(organizationId)}/catalog/new`}>
            <Plus className="size-4" />
            New source
          </Link>
        </Button>
      }
      eyebrow="MCP Catalog"
      title="Catalog"
      workspaceContext={workspaceContext}
    >
      <CatalogSourcesClient organizationId={organizationId} sources={sources} />
    </AppShell>
  );
}
