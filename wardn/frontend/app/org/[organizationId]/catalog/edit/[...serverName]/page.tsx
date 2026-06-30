import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { CatalogSourceForm } from "@/app/catalog/catalog-source-form";
import type { MCPCatalogSource } from "@/app/catalog/catalog-source-types";
import { getSecretStores } from "@/app/organizations/data";
import {
  backendCookieHeader,
  backendPath,
  getWorkspaceContext,
} from "@/lib/workspace-context";

type EditCatalogSourcePageProps = {
  params: Promise<{
    organizationId: string;
    serverName: string[];
  }>;
};

async function getCatalogSource(organizationId: string, sourceId: string) {
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/mcp/catalog/sources/${encodeURIComponent(sourceId)}`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (response.status === 404) {
      notFound();
    }
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as MCPCatalogSource;
  } catch {
    return null;
  }
}

export default async function EditCatalogSourcePage({
  params,
}: EditCatalogSourcePageProps) {
  const { organizationId, serverName } = await params;
  const sourceId = serverName[0] ? decodeURIComponent(serverName[0]) : "";
  const [workspaceContext, source, secretStores] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getCatalogSource(organizationId, sourceId),
    getSecretStores(organizationId),
  ]);

  if (!source) {
    notFound();
  }

  return (
    <AppShell
      active="catalog"
      eyebrow="MCP Catalog"
      title="Edit source"
      workspaceContext={workspaceContext}
    >
      <CatalogSourceForm
        initialSource={source}
        mode="edit"
        organizationId={organizationId}
        secretStores={secretStores}
      />
    </AppShell>
  );
}
