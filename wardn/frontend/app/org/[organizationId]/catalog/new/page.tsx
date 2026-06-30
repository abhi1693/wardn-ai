import { AppShell } from "@/app/components/app-shell";
import { CatalogSourceForm } from "@/app/catalog/catalog-source-form";
import { getSecretStores } from "@/app/organizations/data";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewCatalogSourcePageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewCatalogSourcePage({
  params,
}: NewCatalogSourcePageProps) {
  const { organizationId } = await params;
  const [workspaceContext, secretStores] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getSecretStores(organizationId),
  ]);

  return (
    <AppShell
      active="catalog"
      eyebrow="MCP Catalog"
      title="New source"
      workspaceContext={workspaceContext}
    >
      <CatalogSourceForm
        mode="create"
        organizationId={organizationId}
        secretStores={secretStores}
      />
    </AppShell>
  );
}
