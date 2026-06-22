import { NewVersionPageView } from "@/app/registry/new-version-page-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewOrganizationRegistryServerVersionPageProps = {
  params: Promise<{ organizationId: string; serverName: string[] }>;
  searchParams: Promise<{ version?: string }>;
};

export default async function NewOrganizationRegistryServerVersionPage({
  params,
  searchParams,
}: NewOrganizationRegistryServerVersionPageProps) {
  const { organizationId, serverName } = await params;
  const { version } = await searchParams;
  const decodedName = serverName.map(decodeURIComponent).join("/");

  return (
    <NewVersionPageView
      createSuccessPath={`/org/${encodeURIComponent(organizationId)}/registry`}
      serverName={decodedName}
      version={version || "latest"}
      workspaceContext={await getWorkspaceContext({ organizationId })}
    />
  );
}
